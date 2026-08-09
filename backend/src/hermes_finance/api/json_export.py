"""Pydantic contract and read-only mapping for the F03 JSON export."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.api.dashboard import DashboardOut
from hermes_finance.api.settings import MoneyValue
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    Account,
    AppSettings,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpectedCashFlow,
    ExpenseEntry,
    Goal,
    IisContribution,
    IisProfile,
    IncomeEntry,
    Instrument,
    InvestmentCashFlow,
    MonthlyComment,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    SavingAllocation,
    TaxBenefit,
    TaxBracket,
)
from hermes_finance.services.markdown_export import MarkdownReport

JSON_SCHEMA_VERSION: Literal["1.0"] = "1.0"


class ExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawAppSettings(ExportModel):
    id: int
    base_currency: str
    locale: str
    timezone: str
    passive_income_goal: MoneyValue
    formula_version: str


class RawReportingMonth(ExportModel):
    id: int
    year: int
    month: int
    period_start: date
    period_end: date
    snapshot_date: date
    status: str
    source: str
    created_at: datetime
    updated_at: datetime


class RawAccount(ExportModel):
    id: int
    name: str
    account_type: str
    external_code: str | None
    status: str
    include_in_capital: bool
    include_in_returns: bool
    notes: str | None


class RawIisProfile(ExportModel):
    id: int
    account_id: int
    iis_type: str
    opened_at: date
    eligible_close_at: date | None
    notes: str | None


class RawIisContribution(ExportModel):
    id: int
    account_id: int
    tax_year: int
    amount: MoneyValue
    is_target_reached: bool
    notes: str | None


class RawTaxBenefit(ExportModel):
    id: int
    account_id: int
    tax_year: int
    benefit_type: str
    status: str
    amount: MoneyValue
    received_at: date | None
    notes: str | None


class RawInstrument(ExportModel):
    id: int
    name: str
    instrument_type: str
    isin: str | None
    ticker: str | None
    moex_secid: str | None
    currency: str
    nominal_value: MoneyValue | None
    is_active: bool
    manual_price_allowed: bool
    notes: str | None


class RawPositionSnapshot(ExportModel):
    id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int
    quantity: str
    average_cost_per_unit: MoneyValue
    market_price_per_unit: MoneyValue
    accrued_interest: MoneyValue | None
    market_value: MoneyValue
    cost_basis: MoneyValue
    unrealized_result: MoneyValue
    price_date: date
    price_source: str
    manual_adjustment: bool
    notes: str | None
    updated_at: datetime


class RawDepositSnapshot(ExportModel):
    id: int
    reporting_month_id: int
    account_id: int
    name: str
    deposit_type: str
    balance: MoneyValue
    annual_rate: str
    expected_monthly_interest: MoneyValue
    actual_interest_received: MoneyValue
    notes: str | None
    updated_at: datetime


class RawCashBalance(ExportModel):
    id: int
    reporting_month_id: int
    name: str
    amount: MoneyValue
    include_in_capital: bool
    notes: str | None


class RawIncomeEntry(ExportModel):
    id: int
    reporting_month_id: int
    income_type: str
    name: str
    gross_amount: MoneyValue
    tax_amount: MoneyValue
    net_amount: MoneyValue
    received_at: date | None
    is_recurring: bool
    include_in_cash_flow: bool
    include_in_passive_income: bool
    notes: str | None


class RawInvestmentCashFlow(ExportModel):
    id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int | None
    flow_type: str
    event_date: date
    gross_amount: MoneyValue
    tax_amount: MoneyValue
    commission_amount: MoneyValue
    net_amount: MoneyValue
    currency: str
    source: str
    notes: str | None


class RawExpectedCashFlow(ExportModel):
    id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int
    flow_type: str
    expected_date: date
    gross_amount: MoneyValue
    expected_tax_amount: MoneyValue | None
    expected_net_amount: MoneyValue
    currency: str
    source: str
    source_as_of_date: date
    forecast_version: str
    is_confirmed: bool
    is_approximate: bool
    notes: str | None


class RawExpenseEntry(ExportModel):
    id: int
    reporting_month_id: int
    category: str
    amount: MoneyValue
    expense_type: str
    is_recurring: bool
    notes: str | None


class RawSavingAllocation(ExportModel):
    id: int
    reporting_month_id: int
    destination: str
    amount: MoneyValue
    notes: str | None


class RawDebt(ExportModel):
    id: int
    reporting_month_id: int
    debt_type: str
    name: str
    current_balance: MoneyValue
    include_in_liquid_capital: bool
    notes: str | None


class RawPropertySnapshot(ExportModel):
    id: int
    reporting_month_id: int
    name: str
    estimated_value: MoneyValue
    mortgage_balance: MoneyValue
    monthly_payment: MoneyValue
    notes: str | None


class RawGoal(ExportModel):
    id: int
    name: str
    goal_type: str
    target_value: MoneyValue
    target_date: date | None
    is_active: bool
    calculation_mode: str
    notes: str | None


class RawMonthlyComment(ExportModel):
    id: int
    reporting_month_id: int
    position: int
    text: str


class RawTaxBracket(ExportModel):
    id: int
    year: int
    threshold_from: MoneyValue
    threshold_to: MoneyValue | None
    rate: str


class RawSourceData(ExportModel):
    app_settings: RawAppSettings
    reporting_month: RawReportingMonth
    accounts: list[RawAccount]
    iis_profiles: list[RawIisProfile]
    iis_contributions: list[RawIisContribution]
    tax_benefits: list[RawTaxBenefit]
    instruments: list[RawInstrument]
    position_snapshots: list[RawPositionSnapshot]
    deposit_snapshots: list[RawDepositSnapshot]
    cash_balances: list[RawCashBalance]
    income_entries: list[RawIncomeEntry]
    investment_cash_flows: list[RawInvestmentCashFlow]
    expected_cash_flows: list[RawExpectedCashFlow]
    expense_entries: list[RawExpenseEntry]
    saving_allocations: list[RawSavingAllocation]
    debts: list[RawDebt]
    property_snapshots: list[RawPropertySnapshot]
    goals: list[RawGoal]
    monthly_comments: list[RawMonthlyComment]
    tax_brackets: list[RawTaxBracket]


class ReportIncomeRow(ExportModel):
    name: str
    income_type: str
    gross: MoneyValue
    tax: MoneyValue
    net: MoneyValue


class ReportInvestmentFlowRow(ExportModel):
    event_date: date
    flow_type: str
    gross: MoneyValue
    tax: MoneyValue
    commission: MoneyValue
    net: MoneyValue


class ReportExpenseRow(ExportModel):
    category: str
    expense_type: str
    amount: MoneyValue


class ReportDebtRow(ExportModel):
    name: str
    debt_type: str
    balance: MoneyValue
    included_in_liquid_capital: bool


class ReportGoalRow(ExportModel):
    name: str
    goal_type: str
    target: MoneyValue
    progress_pct: str | None


class ReportData(ExportModel):
    income_rows: list[ReportIncomeRow]
    investment_flow_rows: list[ReportInvestmentFlowRow]
    expense_rows: list[ReportExpenseRow]
    debt_rows: list[ReportDebtRow]
    goal_rows: list[ReportGoalRow]
    comments: list[str]


class DerivedData(ExportModel):
    dashboard: DashboardOut
    report: ReportData


class JsonExport(ExportModel):
    schema_version: Literal["1.0"]
    calculation_version: str
    raw: RawSourceData
    derived: DerivedData


def _money(amount_kopecks: int | None, currency: str = "RUB") -> MoneyValue | None:
    if amount_kopecks is None:
        return None
    return MoneyValue(amount=RubleAmount(amount_kopecks).to_api(), currency=currency)


def _required_money(amount_kopecks: int, currency: str = "RUB") -> MoneyValue:
    value = _money(amount_kopecks, currency)
    assert value is not None
    return value


def _rate(amount_basis_points: int) -> str:
    return format(Decimal(amount_basis_points) / Decimal(100), ".2f")


def _quantity(value: Decimal) -> str:
    return format(value, "f")


def _month_rows(session: Session, model: type[object], month_id: int) -> list[object]:
    return list(
        session.scalars(
            select(model).where(model.reporting_month_id == month_id).order_by(model.id)
        )
    )


def build_raw_source_data(session: Session, month: ReportingMonth) -> RawSourceData:
    """Map persisted source rows without aggregating or changing the session."""
    settings = session.scalar(select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID))
    if settings is None:
        raise RuntimeError("app settings must be prepared before building an export")
    accounts = list(session.scalars(select(Account).order_by(Account.id)))
    instruments = list(session.scalars(select(Instrument).order_by(Instrument.id)))
    return RawSourceData(
        app_settings=RawAppSettings(
            id=settings.id,
            base_currency=settings.base_currency,
            locale=settings.locale,
            timezone=settings.timezone,
            passive_income_goal=_required_money(
                settings.passive_income_goal_kopecks, settings.base_currency
            ),
            formula_version=settings.formula_version,
        ),
        reporting_month=RawReportingMonth.model_validate(month, from_attributes=True),
        accounts=[RawAccount.model_validate(item, from_attributes=True) for item in accounts],
        iis_profiles=[
            RawIisProfile.model_validate(item, from_attributes=True)
            for item in session.scalars(select(IisProfile).order_by(IisProfile.id))
        ],
        iis_contributions=[
            RawIisContribution(
                id=item.id,
                account_id=item.account_id,
                tax_year=item.tax_year,
                amount=_required_money(item.amount_kopecks),
                is_target_reached=item.is_target_reached,
                notes=item.notes,
            )
            for item in session.scalars(select(IisContribution).order_by(IisContribution.id))
        ],
        tax_benefits=[
            RawTaxBenefit(
                id=item.id,
                account_id=item.account_id,
                tax_year=item.tax_year,
                benefit_type=item.benefit_type,
                status=item.status,
                amount=_required_money(item.amount_kopecks),
                received_at=item.received_at,
                notes=item.notes,
            )
            for item in session.scalars(select(TaxBenefit).order_by(TaxBenefit.id))
        ],
        instruments=[
            RawInstrument(
                id=item.id,
                name=item.name,
                instrument_type=item.instrument_type,
                isin=item.isin,
                ticker=item.ticker,
                moex_secid=item.moex_secid,
                currency=item.currency,
                nominal_value=_money(item.nominal_value_kopecks, item.currency),
                is_active=item.is_active,
                manual_price_allowed=item.manual_price_allowed,
                notes=item.notes,
            )
            for item in instruments
        ],
        position_snapshots=[
            RawPositionSnapshot(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                quantity=_quantity(item.quantity),
                average_cost_per_unit=_required_money(item.average_cost_per_unit_kopecks),
                market_price_per_unit=_required_money(item.market_price_per_unit_kopecks),
                accrued_interest=_money(item.accrued_interest_kopecks),
                market_value=_required_money(item.market_value_kopecks),
                cost_basis=_required_money(item.cost_basis_kopecks),
                unrealized_result=_required_money(item.unrealized_result_kopecks),
                price_date=item.price_date,
                price_source=item.price_source,
                manual_adjustment=item.manual_adjustment,
                notes=item.notes,
                updated_at=item.updated_at,
            )
            for item in _month_rows(session, PositionSnapshot, month.id)
        ],
        deposit_snapshots=[
            RawDepositSnapshot(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                account_id=item.account_id,
                name=item.name,
                deposit_type=item.deposit_type,
                balance=_required_money(item.balance_kopecks),
                annual_rate=_rate(item.annual_rate_basis_points),
                expected_monthly_interest=_required_money(item.expected_monthly_interest_kopecks),
                actual_interest_received=_required_money(item.actual_interest_received_kopecks),
                notes=item.notes,
                updated_at=item.updated_at,
            )
            for item in _month_rows(session, DepositSnapshot, month.id)
        ],
        cash_balances=[
            RawCashBalance(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                name=item.name,
                amount=_required_money(item.amount_kopecks, item.currency),
                include_in_capital=item.include_in_capital,
                notes=item.notes,
            )
            for item in _month_rows(session, CashBalance, month.id)
        ],
        income_entries=[
            RawIncomeEntry(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                income_type=item.income_type,
                name=item.name,
                gross_amount=_required_money(item.gross_amount_kopecks),
                tax_amount=_required_money(item.tax_amount_kopecks),
                net_amount=_required_money(item.net_amount_kopecks),
                received_at=item.received_at,
                is_recurring=item.is_recurring,
                include_in_cash_flow=item.include_in_cash_flow,
                include_in_passive_income=item.include_in_passive_income,
                notes=item.notes,
            )
            for item in _month_rows(session, IncomeEntry, month.id)
        ],
        investment_cash_flows=[
            RawInvestmentCashFlow(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                flow_type=item.flow_type,
                event_date=item.event_date,
                gross_amount=_required_money(item.gross_amount_kopecks, item.currency),
                tax_amount=_required_money(item.tax_amount_kopecks, item.currency),
                commission_amount=_required_money(item.commission_amount_kopecks, item.currency),
                net_amount=_required_money(item.net_amount_kopecks, item.currency),
                currency=item.currency,
                source=item.source,
                notes=item.notes,
            )
            for item in _month_rows(session, InvestmentCashFlow, month.id)
        ],
        expected_cash_flows=[
            RawExpectedCashFlow(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                account_id=item.account_id,
                instrument_id=item.instrument_id,
                flow_type=item.flow_type,
                expected_date=item.expected_date,
                gross_amount=_required_money(item.gross_amount_kopecks, item.currency),
                expected_tax_amount=_money(item.expected_tax_amount_kopecks, item.currency),
                expected_net_amount=_required_money(
                    item.expected_net_amount_kopecks, item.currency
                ),
                currency=item.currency,
                source=item.source,
                source_as_of_date=item.source_as_of_date,
                forecast_version=item.forecast_version,
                is_confirmed=item.is_confirmed,
                is_approximate=item.is_approximate,
                notes=item.notes,
            )
            for item in _month_rows(session, ExpectedCashFlow, month.id)
        ],
        expense_entries=[
            RawExpenseEntry(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                category=item.category,
                amount=_required_money(item.amount_kopecks),
                expense_type=item.expense_type,
                is_recurring=item.is_recurring,
                notes=item.notes,
            )
            for item in _month_rows(session, ExpenseEntry, month.id)
        ],
        saving_allocations=[
            RawSavingAllocation(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                destination=item.destination,
                amount=_required_money(item.amount_kopecks),
                notes=item.notes,
            )
            for item in _month_rows(session, SavingAllocation, month.id)
        ],
        debts=[
            RawDebt(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                debt_type=item.debt_type,
                name=item.name,
                current_balance=_required_money(item.current_balance_kopecks),
                include_in_liquid_capital=item.include_in_liquid_capital,
                notes=item.notes,
            )
            for item in _month_rows(session, Debt, month.id)
        ],
        property_snapshots=[
            RawPropertySnapshot(
                id=item.id,
                reporting_month_id=item.reporting_month_id,
                name=item.name,
                estimated_value=_required_money(item.estimated_value_kopecks),
                mortgage_balance=_required_money(item.mortgage_balance_kopecks),
                monthly_payment=_required_money(item.monthly_payment_kopecks),
                notes=item.notes,
            )
            for item in _month_rows(session, PropertySnapshot, month.id)
        ],
        goals=[
            RawGoal(
                id=item.id,
                name=item.name,
                goal_type=item.goal_type,
                target_value=_required_money(item.target_value_kopecks),
                target_date=item.target_date,
                is_active=item.is_active,
                calculation_mode=item.calculation_mode,
                notes=item.notes,
            )
            for item in session.scalars(select(Goal).order_by(Goal.id))
        ],
        monthly_comments=[
            RawMonthlyComment.model_validate(item, from_attributes=True)
            for item in _month_rows(session, MonthlyComment, month.id)
        ],
        tax_brackets=[
            RawTaxBracket(
                id=item.id,
                year=item.year,
                threshold_from=_required_money(item.threshold_from_kopecks, settings.base_currency),
                threshold_to=_money(item.threshold_to_kopecks, settings.base_currency),
                rate=_rate(item.rate_bps),
            )
            for item in session.scalars(
                select(TaxBracket)
                .where(TaxBracket.year == month.year)
                .order_by(TaxBracket.threshold_from_kopecks)
            )
        ],
    )


def build_report_data(report: MarkdownReport) -> ReportData:
    return ReportData(
        income_rows=[
            ReportIncomeRow(
                name=item.name,
                income_type=item.income_type,
                gross=_required_money(item.gross.kopecks),
                tax=_required_money(item.tax.kopecks),
                net=_required_money(item.net.kopecks),
            )
            for item in report.income_rows
        ],
        investment_flow_rows=[
            ReportInvestmentFlowRow(
                event_date=item.event_date,
                flow_type=item.flow_type,
                gross=_required_money(item.gross.kopecks),
                tax=_required_money(item.tax.kopecks),
                commission=_required_money(item.commission.kopecks),
                net=_required_money(item.net.kopecks),
            )
            for item in report.investment_flow_rows
        ],
        expense_rows=[
            ReportExpenseRow(
                category=item.category,
                expense_type=item.expense_type,
                amount=_required_money(item.amount.kopecks),
            )
            for item in report.expense_rows
        ],
        debt_rows=[
            ReportDebtRow(
                name=item.name,
                debt_type=item.debt_type,
                balance=_required_money(item.balance.kopecks),
                included_in_liquid_capital=item.included_in_liquid_capital,
            )
            for item in report.debt_rows
        ],
        goal_rows=[
            ReportGoalRow(
                name=item.name,
                goal_type=item.goal_type,
                target=_required_money(item.target.kopecks),
                progress_pct=(
                    format(item.progress_pct, "f") if item.progress_pct is not None else None
                ),
            )
            for item in report.goal_rows
        ],
        comments=list(report.comments),
    )


def build_json_export(
    *,
    raw: RawSourceData,
    dashboard: DashboardOut,
    report: MarkdownReport,
) -> JsonExport:
    return JsonExport(
        schema_version=JSON_SCHEMA_VERSION,
        calculation_version=dashboard.calculation_version,
        raw=raw,
        derived=DerivedData(dashboard=dashboard, report=build_report_data(report)),
    )
