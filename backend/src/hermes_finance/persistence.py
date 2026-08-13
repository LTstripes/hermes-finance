from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hermes_finance.domain.iis import TaxBenefitStatus

APP_SETTINGS_ID: Final = 1
DEFAULT_BASE_CURRENCY: Final = "RUB"
DEFAULT_LOCALE: Final = "ru-RU"
DEFAULT_TIMEZONE: Final = "Europe/Moscow"
DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS: Final = 10_000_000
DEFAULT_FORMULA_VERSION: Final = "v1"
DEFAULT_PASSIVE_INCOME_HISTORY_START_MONTH: Final = None


class Base(DeclarativeBase):
    pass


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint(
            f"id = {APP_SETTINGS_ID}",
            name="ck_app_settings_singleton_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=APP_SETTINGS_ID)
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    locale: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_LOCALE, server_default=text("'ru-RU'")
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default=DEFAULT_TIMEZONE, server_default=text("'Europe/Moscow'")
    )
    passive_income_goal_kopecks: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
        server_default=text(str(DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS)),
    )
    formula_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_FORMULA_VERSION, server_default=text("'v1'")
    )
    passive_income_history_start_month: Mapped[str | None] = mapped_column(
        String(7), nullable=True, default=DEFAULT_PASSIVE_INCOME_HISTORY_START_MONTH
    )


class ReportingMonth(Base):
    __tablename__ = "reporting_months"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_reporting_months_year_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_reporting_months_month_range"),
        CheckConstraint(
            "status IN ('draft', 'closed')",
            name="ck_reporting_months_status",
        ),
        CheckConstraint(
            "source IN ('manual', 'excel_migration', 'alfa_pdf')",
            name="ck_reporting_months_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default=text("'draft'")
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default=text("'manual'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class SalaryTaxYearContext(Base):
    __tablename__ = "salary_tax_year_contexts"
    __table_args__ = (
        CheckConstraint(
            "tax_year BETWEEN 1 AND 9999",
            name="ck_salary_tax_year_contexts_tax_year_range",
        ),
        CheckConstraint(
            "effective_from_month BETWEEN 1 AND 12",
            name="ck_salary_tax_year_contexts_effective_month_range",
        ),
        CheckConstraint(
            "opening_taxable_gross_kopecks >= 0",
            name="ck_salary_tax_year_contexts_opening_gross_nonnegative",
        ),
        CheckConstraint(
            "effective_from_month != 1 OR opening_taxable_gross_kopecks = 0",
            name="ck_salary_tax_year_contexts_january_zero_opening",
        ),
    )

    tax_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_from_month: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_taxable_gross_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("external_code", name="uq_accounts_external_code"),
        CheckConstraint(
            "account_type IN ('brokerage', 'iis', 'deposit', 'savings', 'cash', 'other')",
            name="ck_accounts_account_type",
        ),
        CheckConstraint(
            "status IN ('active', 'frozen', 'closed', 'hidden')",
            name="ck_accounts_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    external_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )
    include_in_capital: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("1")
    )
    include_in_returns: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("1")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class IisProfile(Base):
    __tablename__ = "iis_profiles"
    __table_args__ = (UniqueConstraint("account_id", name="uq_iis_profiles_account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    iis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    opened_at: Mapped[date] = mapped_column(Date, nullable=False)
    eligible_close_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class IisContribution(Base):
    __tablename__ = "iis_contributions"
    __table_args__ = (
        UniqueConstraint("account_id", "tax_year", name="uq_iis_contributions_account_year"),
        CheckConstraint("tax_year BETWEEN 1900 AND 9999", name="ck_iis_contributions_tax_year"),
        CheckConstraint("amount_kopecks >= 0", name="ck_iis_contributions_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_target_reached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class TaxBenefit(Base):
    __tablename__ = "tax_benefits"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "tax_year",
            "benefit_type",
            name="uq_tax_benefits_account_year_type",
        ),
        CheckConstraint("tax_year BETWEEN 1900 AND 9999", name="ck_tax_benefits_tax_year"),
        CheckConstraint("amount_kopecks >= 0", name="ck_tax_benefits_amount_nonnegative"),
        CheckConstraint(
            "status IN ('planned', 'submitted', 'received', 'rejected')",
            name="ck_tax_benefits_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    benefit_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    @property
    def counts_as_received(self) -> bool:
        return TaxBenefitStatus(self.status).counts_as_received


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("isin", name="uq_instruments_isin"),
        CheckConstraint(
            "instrument_type IN ('stock', 'bond', 'fund', 'currency', 'gold', 'other')",
            name="ck_instruments_instrument_type",
        ),
        CheckConstraint(
            "nominal_value_kopecks IS NULL OR nominal_value_kopecks >= 0",
            name="ck_instruments_nominal_value_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(16), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    moex_secid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    nominal_value_kopecks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("1"))
    manual_price_allowed: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("1")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            name="uq_position_snapshots_month_account_instrument",
        ),
        CheckConstraint("quantity >= 0", name="ck_position_snapshots_quantity_nonnegative"),
        CheckConstraint(
            "average_cost_per_unit_kopecks >= 0",
            name="ck_position_snapshots_average_cost_nonnegative",
        ),
        CheckConstraint(
            "market_price_per_unit_kopecks >= 0",
            name="ck_position_snapshots_market_price_nonnegative",
        ),
        CheckConstraint(
            "accrued_interest_kopecks IS NULL OR accrued_interest_kopecks >= 0",
            name="ck_position_snapshots_accrued_interest_nonnegative",
        ),
        CheckConstraint(
            "market_value_kopecks >= 0",
            name="ck_position_snapshots_market_value_nonnegative",
        ),
        CheckConstraint(
            "cost_basis_kopecks >= 0", name="ck_position_snapshots_cost_basis_nonnegative"
        ),
        CheckConstraint(
            "price_source IN ('manual', 'moex', 'alfa_pdf')",
            name="ck_position_snapshots_price_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    average_cost_per_unit_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_price_per_unit_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accrued_interest_kopecks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    market_value_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_basis_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unrealized_result_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default=text("'manual'")
    )
    manual_adjustment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class DepositSnapshot(Base):
    __tablename__ = "deposit_snapshots"
    __table_args__ = (
        CheckConstraint(
            "deposit_type IN ('deposit', 'savings')",
            name="ck_deposit_snapshots_deposit_type",
        ),
        CheckConstraint("balance_kopecks >= 0", name="ck_deposit_snapshots_balance_nonnegative"),
        CheckConstraint(
            "annual_rate_basis_points >= 0",
            name="ck_deposit_snapshots_annual_rate_nonnegative",
        ),
        CheckConstraint(
            "expected_monthly_interest_kopecks >= 0",
            name="ck_deposit_snapshots_expected_interest_nonnegative",
        ),
        CheckConstraint(
            "actual_interest_received_kopecks >= 0",
            name="ck_deposit_snapshots_actual_interest_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    deposit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    balance_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    annual_rate_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_monthly_interest_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_interest_received_kopecks: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CashBalance(Base):
    __tablename__ = "cash_balances"
    __table_args__ = (
        CheckConstraint("amount_kopecks >= 0", name="ck_cash_balances_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    include_in_capital: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class IncomeEntry(Base):
    __tablename__ = "income_entries"
    __table_args__ = (
        CheckConstraint(
            "income_type IN ('salary', 'bonus', 'side_income', 'cashback', 'other')",
            name="ck_income_entries_income_type",
        ),
        CheckConstraint("gross_amount_kopecks >= 0", name="ck_income_entries_gross_nonnegative"),
        CheckConstraint("tax_amount_kopecks >= 0", name="ck_income_entries_tax_nonnegative"),
        CheckConstraint("net_amount_kopecks >= 0", name="ck_income_entries_net_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    income_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    gross_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    include_in_cash_flow: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    include_in_passive_income: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class InvestmentCashFlow(Base):
    __tablename__ = "investment_cash_flows"
    __table_args__ = (
        CheckConstraint(
            "flow_type IN ('interest', 'coupon', 'dividend', 'redemption', 'deposit', "
            "'withdrawal', 'commission', 'tax', 'realized_profit', 'realized_loss', 'other')",
            name="ck_investment_cash_flows_flow_type",
        ),
        CheckConstraint(
            "gross_amount_kopecks >= 0", name="ck_investment_cash_flows_gross_nonnegative"
        ),
        CheckConstraint("tax_amount_kopecks >= 0", name="ck_investment_cash_flows_tax_nonnegative"),
        CheckConstraint(
            "commission_amount_kopecks >= 0",
            name="ck_investment_cash_flows_commission_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=True
    )
    flow_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    gross_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commission_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class ExpectedCashFlow(Base):
    __tablename__ = "expected_cash_flows"
    __table_args__ = (
        UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "flow_type",
            "expected_date",
            "forecast_version",
            name="uq_expected_cash_flows_snapshot_event",
        ),
        CheckConstraint(
            "flow_type IN ('coupon', 'dividend', 'interest', 'redemption', 'other')",
            name="ck_expected_cash_flows_flow_type",
        ),
        CheckConstraint(
            "gross_amount_kopecks >= 0", name="ck_expected_cash_flows_gross_nonnegative"
        ),
        CheckConstraint(
            "expected_tax_amount_kopecks IS NULL OR expected_tax_amount_kopecks >= 0",
            name="ck_expected_cash_flows_tax_nonnegative",
        ),
        CheckConstraint(
            "expected_net_amount_kopecks >= 0", name="ck_expected_cash_flows_net_nonnegative"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    flow_type: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    gross_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_tax_amount_kopecks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expected_net_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    forecast_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    is_approximate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class ExpenseEntry(Base):
    __tablename__ = "expense_entries"
    __table_args__ = (
        CheckConstraint(
            "expense_type IN ('mandatory', 'comfortable', 'other')",
            name="ck_expense_entries_expense_type",
        ),
        CheckConstraint("amount_kopecks >= 0", name="ck_expense_entries_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expense_type: Mapped[str] = mapped_column(String(16), nullable=False)
    is_recurring: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class SavingAllocation(Base):
    __tablename__ = "saving_allocations"
    __table_args__ = (
        CheckConstraint("amount_kopecks >= 0", name="ck_saving_allocations_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    destination: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class Debt(Base):
    __tablename__ = "debts"
    __table_args__ = (
        CheckConstraint(
            "debt_type IN ('credit_card', 'other')",
            name="ck_debts_debt_type",
        ),
        CheckConstraint(
            "current_balance_kopecks >= 0", name="ck_debts_current_balance_nonnegative"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    debt_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    current_balance_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    include_in_liquid_capital: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class PropertySnapshot(Base):
    __tablename__ = "property_snapshots"
    __table_args__ = (
        CheckConstraint(
            "estimated_value_kopecks >= 0", name="ck_property_snapshots_value_nonnegative"
        ),
        CheckConstraint(
            "mortgage_balance_kopecks >= 0", name="ck_property_snapshots_mortgage_nonnegative"
        ),
        CheckConstraint(
            "monthly_payment_kopecks >= 0", name="ck_property_snapshots_payment_nonnegative"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    estimated_value_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mortgage_balance_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_payment_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (
        Index(
            "uq_goals_single_main",
            "is_main",
            unique=True,
            sqlite_where=text("is_main = 1"),
        ),
        CheckConstraint(
            "goal_type IN ('passive_income', 'capital', 'expense_coverage', "
            "'mortgage_coverage', 'other')",
            name="ck_goals_goal_type",
        ),
        CheckConstraint("target_value_kopecks >= 0", name="ck_goals_target_value_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    goal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_value_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    is_main: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    calculation_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class MonthlyComment(Base):
    __tablename__ = "monthly_comments"
    __table_args__ = (
        UniqueConstraint(
            "reporting_month_id", "position", name="uq_monthly_comments_month_position"
        ),
        CheckConstraint("position >= 1", name="ck_monthly_comments_position_positive"),
        CheckConstraint("length(text) > 0", name="ck_monthly_comments_text_nonempty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String(2000), nullable=False)


class LegacyMigrationRun(Base):
    __tablename__ = "legacy_migration_runs"
    __table_args__ = (
        UniqueConstraint("source_sha256", name="uq_legacy_migration_runs_source_sha256"),
        CheckConstraint("month_count > 0", name="ck_legacy_migration_runs_month_count_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    policy: Mapped[str] = mapped_column(String(32), nullable=False)
    backup_id: Mapped[str] = mapped_column(String(128), nullable=False)
    month_count: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class TaxBracket(Base):
    __tablename__ = "tax_brackets"
    __table_args__ = (
        UniqueConstraint("year", "threshold_from_kopecks", name="uq_tax_brackets_year_from"),
        CheckConstraint("threshold_from_kopecks >= 0", name="ck_tax_brackets_from_nonnegative"),
        CheckConstraint(
            "threshold_to_kopecks IS NULL OR threshold_to_kopecks > threshold_from_kopecks",
            name="ck_tax_brackets_to_after_from",
        ),
        CheckConstraint("rate_bps >= 0", name="ck_tax_brackets_rate_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_from_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    threshold_to_kopecks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
