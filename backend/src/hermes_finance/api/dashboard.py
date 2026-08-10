"""Month summary and dashboard API (D07).

Maps the C10 monthly summary and the D07 dashboard assembly onto HTTP.
No financial formulas live here — only MoneyValue conversion and nesting.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain.monthly_summary import MonthlySummaryResult
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.dashboard import DashboardResult, build_dashboard
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION, monthly_summary
from hermes_finance.services.reporting_months import get_reporting_month

router = APIRouter(prefix="/api/months", tags=["dashboard"])


def _money(amount: RubleAmount | int) -> MoneyValue:
    if isinstance(amount, RubleAmount):
        kopecks = amount.kopecks
    else:
        kopecks = amount
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _money_opt(amount: RubleAmount | None) -> MoneyValue | None:
    return None if amount is None else _money(amount)


def _dec_str(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


# --- nested summary models ---


class LiquidCapitalBreakdownOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cash: MoneyValue
    deposits: MoneyValue
    securities: MoneyValue
    other_liquid_assets: MoneyValue


class AccountAmountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    amount: MoneyValue


class LiquidCapitalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_assets: MoneyValue
    total_debts_included: MoneyValue
    liquid_capital_net: MoneyValue
    breakdown: LiquidCapitalBreakdownOut
    accounts: list[AccountAmountOut]


class ForecastBreakdownOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_deposit_interest: MoneyValue
    expected_coupon_net: MoneyValue
    expected_dividend_component: MoneyValue
    other_expected_capital_income: MoneyValue


class ForecastOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annual_total: MoneyValue
    monthly_total: MoneyValue
    breakdown: ForecastBreakdownOut
    is_approximate: bool
    warnings: list[str]
    dividend_average: MoneyValue


class CoverageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_monthly: MoneyValue
    actual_average: MoneyValue
    mandatory_expenses: MoneyValue
    coverage_pct: str | None
    passive_income_minus_mandatory_expenses: MoneyValue
    goal_target: MoneyValue
    goal_progress_pct: str | None
    is_approximate: bool
    warnings: list[str]


class CashBalanceBreakdownOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    salary_net: MoneyValue
    bonus_net: MoneyValue
    side_income_net: MoneyValue
    cashback: MoneyValue
    other_income: MoneyValue
    passive_income: MoneyValue
    mandatory_expenses: MoneyValue
    other_expenses: MoneyValue
    saving_allocations: MoneyValue


class CashBalanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: MoneyValue
    breakdown: CashBalanceBreakdownOut


class TaxPartOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_kopecks: MoneyValue
    to_kopecks: MoneyValue | None
    rate_bps: int
    taxable: MoneyValue
    tax: MoneyValue


class SalaryTaxOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax: MoneyValue
    calculated_net: MoneyValue
    parts: list[TaxPartOut]


class NormalizedBonusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_average: MoneyValue
    sum_total: MoneyValue
    count_months: int
    is_complete_12m: bool
    warnings: list[str]


class IisBreakdownOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unrealized: MoneyValue
    coupons: MoneyValue
    dividends: MoneyValue
    realized_pnl: MoneyValue
    received_tax_benefits: MoneyValue
    planned_tax_benefits: MoneyValue
    submitted_tax_benefits: MoneyValue


class IisOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_result_without_tax_benefit: MoneyValue
    portfolio_result_with_tax_benefit: MoneyValue
    breakdown: IisBreakdownOut


class MonthRefOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    year: int
    month: int
    status: str
    snapshot_date: date
    source: str


class MonthlySummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: MonthRefOut
    liquid_capital: LiquidCapitalOut
    liquid_capital_delta: MoneyValue | None
    passive_income_actual: MoneyValue
    passive_income_delta: MoneyValue | None
    passive_income_average: MoneyValue
    passive_income_average_months: int
    passive_income_average_complete: bool
    forecast: ForecastOut
    coverage: CoverageOut
    cash_balance: CashBalanceOut
    salary_tax: SalaryTaxOut
    salary_actual_net: MoneyValue
    normalized_bonus: NormalizedBonusOut
    iis: list[IisOut]
    warnings: list[str]
    calculation_version: str


class HistoricalPointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    reporting_month_id: int
    liquid_capital_net: MoneyValue
    passive_income_actual: MoneyValue


class AssetClassSliceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_class: str
    amount: MoneyValue


class InstrumentClassResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_type: str
    market_value: MoneyValue
    cost_basis: MoneyValue
    unrealized_result: MoneyValue
    realized_result: MoneyValue


class ExpectedPaymentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    expected_date: date
    flow_type: str
    account_id: int
    instrument_id: int
    gross_amount: MoneyValue
    expected_tax_amount: MoneyValue | None
    expected_net_amount: MoneyValue
    is_confirmed: bool
    is_approximate: bool
    source: str
    forecast_version: str


class MortgageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mortgage_balance: MoneyValue
    coverage_pct: str | None
    gap: MoneyValue


class KpiOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    liquid_capital_net: MoneyValue
    liquid_capital_delta: MoneyValue | None
    forecast_monthly_passive_income: MoneyValue
    passive_income_average: MoneyValue
    passive_income_average_months: int
    passive_income_average_complete: bool
    goal_progress_pct: str | None
    goal_target: MoneyValue
    mandatory_expenses: MoneyValue
    mandatory_expense_coverage_pct: str | None
    mortgage_balance: MoneyValue
    mortgage_coverage_pct: str | None


class AccountResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    account_name: str
    account_type: str
    cash_income: MoneyValue
    unrealized_result: MoneyValue


class DashboardOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: MonthRefOut
    kpis: KpiOut
    summary: MonthlySummaryOut
    historical_series: list[HistoricalPointOut]
    asset_allocation: list[AssetClassSliceOut]
    result_by_account: list[AccountResultOut]
    result_by_instrument_class: list[InstrumentClassResultOut]
    expected_payments: list[ExpectedPaymentOut]
    mortgage: MortgageOut
    warnings: list[str]
    calculation_version: str


def _liquid_out(result: object) -> LiquidCapitalOut:
    return LiquidCapitalOut(
        total_assets=_money(result.total_assets),
        total_debts_included=_money(result.total_debts_included),
        liquid_capital_net=_money(result.liquid_capital_net),
        breakdown=LiquidCapitalBreakdownOut(
            cash=_money(result.breakdown.cash),
            deposits=_money(result.breakdown.deposits),
            securities=_money(result.breakdown.securities),
            other_liquid_assets=_money(result.breakdown.other_liquid_assets),
        ),
        accounts=[
            AccountAmountOut(account_id=item.account_id, amount=_money(item.amount))
            for item in result.accounts
        ],
    )


def _summary_out(month: object, summary: MonthlySummaryResult) -> MonthlySummaryOut:
    forecast = summary.forecast
    coverage = summary.coverage
    cash = summary.cash_balance
    tax = summary.salary_tax
    bonus = summary.normalized_bonus
    return MonthlySummaryOut(
        month=MonthRefOut(
            id=month.id,
            year=month.year,
            month=month.month,
            status=month.status,
            snapshot_date=month.snapshot_date,
            source=month.source,
        ),
        liquid_capital=_liquid_out(summary.liquid_capital),
        liquid_capital_delta=_money_opt(summary.liquid_capital_delta),
        passive_income_actual=_money(summary.passive_income_actual),
        passive_income_delta=_money_opt(summary.passive_income_delta),
        passive_income_average=_money(summary.passive_income_average),
        passive_income_average_months=summary.passive_income_average_months,
        passive_income_average_complete=summary.passive_income_average_complete,
        forecast=ForecastOut(
            annual_total=_money(forecast.annual_total),
            monthly_total=_money(forecast.monthly_total),
            breakdown=ForecastBreakdownOut(
                expected_deposit_interest=_money(forecast.breakdown.expected_deposit_interest),
                expected_coupon_net=_money(forecast.breakdown.expected_coupon_net),
                expected_dividend_component=_money(forecast.breakdown.expected_dividend_component),
                other_expected_capital_income=_money(
                    forecast.breakdown.other_expected_capital_income
                ),
            ),
            is_approximate=forecast.is_approximate,
            warnings=list(forecast.warnings),
            dividend_average=_money(forecast.dividend_average),
        ),
        coverage=CoverageOut(
            forecast_monthly=_money(coverage.forecast_monthly),
            actual_average=_money(coverage.actual_average),
            mandatory_expenses=_money(coverage.mandatory_expenses),
            coverage_pct=_dec_str(coverage.coverage_pct),
            passive_income_minus_mandatory_expenses=_money(
                coverage.passive_income_minus_mandatory_expenses
            ),
            goal_target=_money(coverage.goal_target),
            goal_progress_pct=_dec_str(coverage.goal_progress_pct),
            is_approximate=coverage.is_approximate,
            warnings=list(coverage.warnings),
        ),
        cash_balance=CashBalanceOut(
            total=_money(cash.total),
            breakdown=CashBalanceBreakdownOut(
                salary_net=_money(cash.breakdown.salary_net),
                bonus_net=_money(cash.breakdown.bonus_net),
                side_income_net=_money(cash.breakdown.side_income_net),
                cashback=_money(cash.breakdown.cashback),
                other_income=_money(cash.breakdown.other_income),
                passive_income=_money(cash.breakdown.passive_income),
                mandatory_expenses=_money(cash.breakdown.mandatory_expenses),
                other_expenses=_money(cash.breakdown.other_expenses),
                saving_allocations=_money(cash.breakdown.saving_allocations),
            ),
        ),
        salary_tax=SalaryTaxOut(
            tax=_money(tax.tax_kopecks),
            calculated_net=_money(tax.calculated_net_kopecks),
            parts=[
                TaxPartOut(
                    from_kopecks=_money(part.from_kopecks),
                    to_kopecks=_money_opt(
                        RubleAmount(part.to_kopecks) if part.to_kopecks is not None else None
                    ),
                    rate_bps=part.rate_bps,
                    taxable=_money(part.taxable_kopecks),
                    tax=_money(part.tax_kopecks),
                )
                for part in tax.parts
            ],
        ),
        salary_actual_net=_money(summary.salary_actual_net),
        normalized_bonus=NormalizedBonusOut(
            monthly_average=_money(bonus.monthly_average),
            sum_total=_money(bonus.sum_total),
            count_months=bonus.count_months,
            is_complete_12m=bonus.is_complete_12m,
            warnings=list(bonus.warnings),
        ),
        iis=[
            IisOut(
                portfolio_result_without_tax_benefit=_money(
                    item.portfolio_result_without_tax_benefit
                ),
                portfolio_result_with_tax_benefit=_money(item.portfolio_result_with_tax_benefit),
                breakdown=IisBreakdownOut(
                    unrealized=_money(item.breakdown.unrealized),
                    coupons=_money(item.breakdown.coupons),
                    dividends=_money(item.breakdown.dividends),
                    realized_pnl=_money(item.breakdown.realized_pnl),
                    received_tax_benefits=_money(item.breakdown.received_tax_benefits),
                    planned_tax_benefits=_money(item.breakdown.planned_tax_benefits),
                    submitted_tax_benefits=_money(item.breakdown.submitted_tax_benefits),
                ),
            )
            for item in summary.iis
        ],
        warnings=list(summary.warnings),
        calculation_version=summary.calculation_version,
    )


@router.get("/{month_id}/summary", response_model=MonthlySummaryOut)
def get_month_summary(
    month_id: int,
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    session: Session = Depends(session_for_request),
) -> MonthlySummaryOut:
    month = get_reporting_month(session, month_id)
    summary = monthly_summary(session, month_id, forecast_version=forecast_version)
    return _summary_out(month, summary)


def dashboard_to_out(dashboard: DashboardResult) -> DashboardOut:
    summary_out = _summary_out(dashboard.month, dashboard.summary)
    return DashboardOut(
        month=summary_out.month,
        kpis=KpiOut(
            liquid_capital_net=summary_out.liquid_capital.liquid_capital_net,
            liquid_capital_delta=summary_out.liquid_capital_delta,
            forecast_monthly_passive_income=summary_out.forecast.monthly_total,
            passive_income_average=summary_out.passive_income_average,
            passive_income_average_months=summary_out.passive_income_average_months,
            passive_income_average_complete=summary_out.passive_income_average_complete,
            goal_progress_pct=summary_out.coverage.goal_progress_pct,
            goal_target=summary_out.coverage.goal_target,
            mandatory_expenses=summary_out.coverage.mandatory_expenses,
            mandatory_expense_coverage_pct=summary_out.coverage.coverage_pct,
            mortgage_balance=_money(dashboard.mortgage.mortgage_balance),
            mortgage_coverage_pct=_dec_str(dashboard.mortgage.coverage_pct),
        ),
        summary=summary_out,
        historical_series=[
            HistoricalPointOut(
                year=point.year,
                month=point.month,
                reporting_month_id=point.reporting_month_id,
                liquid_capital_net=_money(point.liquid_capital_net),
                passive_income_actual=_money(point.passive_income_actual),
            )
            for point in dashboard.historical_series
        ],
        asset_allocation=[
            AssetClassSliceOut(asset_class=item.asset_class, amount=_money(item.amount))
            for item in dashboard.asset_allocation
        ],
        result_by_account=[
            AccountResultOut(
                account_id=item.account_id,
                account_name=item.account_name,
                account_type=item.account_type,
                cash_income=_money(item.cash_income),
                unrealized_result=_money(item.unrealized_result),
            )
            for item in dashboard.result_by_account
        ],
        result_by_instrument_class=[
            InstrumentClassResultOut(
                instrument_type=item.instrument_type,
                market_value=_money(item.market_value),
                cost_basis=_money(item.cost_basis),
                unrealized_result=_money(item.unrealized_result),
                realized_result=_money(item.realized_result),
            )
            for item in dashboard.result_by_instrument_class
        ],
        expected_payments=[
            ExpectedPaymentOut(
                id=item.id,
                expected_date=item.expected_date,
                flow_type=item.flow_type,
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                gross_amount=_money(item.gross_amount),
                expected_tax_amount=_money_opt(item.expected_tax_amount),
                expected_net_amount=_money(item.expected_net_amount),
                is_confirmed=item.is_confirmed,
                is_approximate=item.is_approximate,
                source=item.source,
                forecast_version=item.forecast_version,
            )
            for item in dashboard.expected_payments
        ],
        mortgage=MortgageOut(
            mortgage_balance=_money(dashboard.mortgage.mortgage_balance),
            coverage_pct=_dec_str(dashboard.mortgage.coverage_pct),
            gap=_money(dashboard.mortgage.gap),
        ),
        warnings=list(dashboard.warnings),
        calculation_version=dashboard.summary.calculation_version,
    )


@router.get("/{month_id}/dashboard", response_model=DashboardOut)
def get_month_dashboard(
    month_id: int,
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    session: Session = Depends(session_for_request),
) -> DashboardOut:
    return dashboard_to_out(build_dashboard(session, month_id, forecast_version=forecast_version))
