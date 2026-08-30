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


class AccountPerformanceScopeMembership(Base):
    """Effective-dated historical performance-scope membership evidence."""

    __tablename__ = "account_performance_scope_memberships"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "effective_from",
            name="uq_account_scope_memberships_account_effective_from",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_account_scope_memberships_effective_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    include_in_returns: Mapped[bool] = mapped_column(nullable=False)


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


class InstrumentMarketMapping(Base):
    """Accepted market-data mapping for one instrument.

    No row means unmapped. A complete identity with excluded=false is mapped.
    excluded=true always wins for refresh eligibility. provider and
    provider_instrument_id are all-or-nothing; provider_venue_id may be null
    for providers that do not need venue context.
    """

    __tablename__ = "instrument_market_mappings"
    __table_args__ = (
        CheckConstraint(
            "("
            "(provider IS NULL AND provider_instrument_id IS NULL "
            "AND provider_venue_id IS NULL) "
            "OR "
            "(provider IS NOT NULL AND provider_instrument_id IS NOT NULL)"
            ")",
            name="ck_instrument_market_mappings_identity_atomic",
        ),
        CheckConstraint(
            "excluded = 1 OR (provider IS NOT NULL AND provider_instrument_id IS NOT NULL)",
            name="ck_instrument_market_mappings_mapped_complete",
        ),
        CheckConstraint(
            "excluded IN (0, 1)",
            name="ck_instrument_market_mappings_excluded_bool",
        ),
    )

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_instrument_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_venue_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class BrokerIdentityMapping(Base):
    """Owner-confirmed broker account/instrument identity mapping (ADR 0016).

    Separate from market-data mappings and statement-import mappings.
    Append-only lifecycle: confirm, revoke, remap. No silent backfill.
    """

    __tablename__ = "broker_identity_mappings"
    __table_args__ = (
        Index("ix_broker_identity_mappings_provider_status", "provider", "status"),
        Index(
            "uq_broker_identity_mappings_effective_forward",
            "provider",
            "subject_kind",
            "provider_identity",
            unique=True,
            sqlite_where=text("status = 'effective'"),
        ),
        Index(
            "uq_broker_identity_mappings_effective_instrument_reverse",
            "provider",
            "hermes_instrument_id",
            unique=True,
            sqlite_where=text("status = 'effective' AND subject_kind = 'instrument'"),
        ),
        CheckConstraint(
            "subject_kind IN ('account', 'instrument')",
            name="ck_broker_identity_mappings_subject_kind",
        ),
        CheckConstraint(
            "status IN ('effective', 'revoked', 'superseded')",
            name="ck_broker_identity_mappings_status",
        ),
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_broker_identity_mappings_provider_present",
        ),
        CheckConstraint(
            "length(trim(provider_identity)) > 0",
            name="ck_broker_identity_mappings_identity_present",
        ),
        CheckConstraint(
            "("
            "subject_kind = 'account' "
            "AND hermes_account_id IS NOT NULL "
            "AND hermes_instrument_id IS NULL"
            ") OR ("
            "subject_kind = 'instrument' "
            "AND hermes_instrument_id IS NOT NULL "
            "AND hermes_account_id IS NULL"
            ")",
            name="ck_broker_identity_mappings_target_shape",
        ),
        CheckConstraint(
            "subject_kind = 'instrument' OR observed_isin IS NULL",
            name="ck_broker_identity_mappings_isin_instruments_only",
        ),
        CheckConstraint(
            "("
            "status = 'revoked' AND revoked_at IS NOT NULL"
            ") OR ("
            "status != 'revoked' AND revoked_at IS NULL AND revoke_reason IS NULL"
            ")",
            name="ck_broker_identity_mappings_revoke_clock",
        ),
        CheckConstraint(
            "("
            "status = 'superseded' AND successor_mapping_id IS NOT NULL"
            ") OR ("
            "status != 'superseded'"
            ")",
            name="ck_broker_identity_mappings_superseded_successor",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    hermes_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    hermes_instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    predecessor_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_identity_mappings.id", ondelete="RESTRICT"), nullable=True
    )
    successor_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_identity_mappings.id", ondelete="RESTRICT"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    @property
    def hermes_target_id(self) -> int:
        if self.subject_kind == "account":
            assert self.hermes_account_id is not None
            return self.hermes_account_id
        assert self.hermes_instrument_id is not None
        return self.hermes_instrument_id


class BrokerBaselineApply(Base):
    """Month-scoped owner-approved current-state baseline provenance (ADR 0016 §8).

    Append-only evidence of a committed baseline apply. Does not store provider
    prices, NKD, P&L, cash, tickers, names, or raw snapshots.
    """

    __tablename__ = "broker_baseline_applies"
    __table_args__ = (
        Index(
            "ix_broker_baseline_applies_month_confirmed",
            "reporting_month_id",
            "confirmed_at",
        ),
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_broker_baseline_applies_provider_present",
        ),
        CheckConstraint(
            "length(trim(apply_fingerprint)) > 0",
            name="ck_broker_baseline_applies_fingerprint_present",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    compatibility_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    apply_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class BrokerBaselineApplyItem(Base):
    """Selected-row evidence for one committed baseline apply (ADR 0016 §8).

    ``position_snapshot_id`` is the applied snapshot id at commit time. It is
    not a live FK: provenance must not block ordinary draft PositionSnapshot
    delete/replace.
    """

    __tablename__ = "broker_baseline_apply_items"
    __table_args__ = (
        Index("ix_broker_baseline_apply_items_apply_id", "baseline_apply_id"),
        CheckConstraint(
            "action IN ('created', 'updated', 'unchanged')",
            name="ck_broker_baseline_apply_items_action",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_broker_baseline_apply_items_quantity_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    baseline_apply_id: Mapped[int] = mapped_column(
        ForeignKey("broker_baseline_applies.id", ondelete="CASCADE"), nullable=False
    )
    position_snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)


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
            "price_source IN ('manual', 'moex', 'alfa_pdf', 't_invest')",
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


class PositionQuoteProvenance(Base):
    """Immutable snapshot-scoped quote provenance written only by apply."""

    __tablename__ = "position_quote_provenance"
    __table_args__ = (
        Index("ix_position_quote_provenance_snapshot_id", "position_snapshot_id"),
        CheckConstraint(
            "normalized_price_kopecks >= 0",
            name="ck_position_quote_provenance_price_nonnegative",
        ),
        CheckConstraint(
            "freshness IN ('ok', 'stale')",
            name="ck_position_quote_provenance_freshness",
        ),
        CheckConstraint(
            "quote_kind IN ('last', 'history')",
            name="ck_position_quote_provenance_quote_kind",
        ),
        CheckConstraint(
            "raw_price_basis IN ('R', 'F')",
            name="ck_position_quote_provenance_basis",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("position_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_instrument_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_venue_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    quote_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_price: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_price_basis: Mapped[str] = mapped_column(String(8), nullable=False)
    normalized_price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    fetched_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    freshness: Mapped[str] = mapped_column(String(16), nullable=False)
    applied_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
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


class ExternalTransferLink(Base):
    """Owner-created identity for the two legs of one account transfer.

    A link is intentionally independent of amount/date matching.  It may be
    created before either leg is entered, while ``status`` records whether the
    owner has supplied a complete opposite-direction pair.
    """

    __tablename__ = "external_transfer_links"
    __table_args__ = (
        UniqueConstraint("transfer_key", name="uq_external_transfer_links_key"),
        CheckConstraint(
            "status IN ('unresolved', 'resolved')",
            name="ck_external_transfer_links_status",
        ),
        CheckConstraint(
            "length(trim(transfer_key)) > 0",
            name="ck_external_transfer_links_key_nonempty",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unresolved", server_default=text("'unresolved'")
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


class ExternalFlow(Base):
    """Explicit owner-managed cash movement across a tracked-account boundary.

    ``boundary_amount_kopecks`` is the actual non-negative amount crossing the
    boundary.  ``kind`` and ``direction`` deliberately store both the
    high-level semantic and its sign-free account direction; the table check
    constraint prevents them from disagreeing.
    """

    __tablename__ = "external_flows"
    __table_args__ = (
        Index("ix_external_flows_month", "reporting_month_id"),
        Index("ix_external_flows_account", "account_id"),
        Index("ix_external_flows_transfer_link", "transfer_link_id"),
        CheckConstraint(
            "kind IN ('external_contribution', 'external_withdrawal')",
            name="ck_external_flows_kind",
        ),
        CheckConstraint(
            "direction IN ('contribution', 'withdrawal')",
            name="ck_external_flows_direction",
        ),
        CheckConstraint(
            "(kind = 'external_contribution' AND direction = 'contribution') OR "
            "(kind = 'external_withdrawal' AND direction = 'withdrawal')",
            name="ck_external_flows_kind_direction",
        ),
        CheckConstraint(
            "boundary_amount_kopecks >= 0",
            name="ck_external_flows_boundary_amount_nonnegative",
        ),
        CheckConstraint(
            "length(trim(currency)) = 3",
            name="ck_external_flows_currency_length",
        ),
        CheckConstraint(
            "scope_membership IN ('unknown', 'stable_in_scope', 'stable_out_of_scope')",
            name="ck_external_flows_scope_membership",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    boundary_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    scope_membership: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unknown", server_default=text("'unknown'")
    )
    transfer_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_transfer_links.id", ondelete="RESTRICT"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def amount_kopecks(self) -> int:
        """Compatibility spelling for callers that use generic amount wording."""

        return self.boundary_amount_kopecks

    @property
    def flow_kind(self) -> str:
        """Compatibility spelling for the explicit persisted ``kind``."""

        return self.kind

    @property
    def transfer_group_id(self) -> int | None:
        """Compatibility spelling for the durable transfer-link identity."""

        return self.transfer_link_id


class ExternalFlowBoundaryGroup(Base):
    """Explicit same-date external-flow group used by observed boundaries."""

    __tablename__ = "external_flow_boundary_groups"
    __table_args__ = (
        Index(
            "ix_external_flow_boundary_groups_month_date",
            "reporting_month_id",
            "boundary_date",
        ),
        CheckConstraint(
            "scope IN ('portfolio', 'account')",
            name="ck_external_flow_boundary_groups_scope",
        ),
        CheckConstraint(
            "(scope = 'portfolio' AND account_id IS NULL) OR "
            "(scope = 'account' AND account_id IS NOT NULL)",
            name="ck_external_flow_boundary_groups_scope_account",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    boundary_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ExternalFlowBoundaryGroupMember(Base):
    """Explicit membership of an external flow in a same-date boundary group."""

    __tablename__ = "external_flow_boundary_group_members"
    __table_args__ = (
        Index(
            "ix_external_flow_boundary_group_members_flow",
            "external_flow_id",
        ),
    )

    boundary_group_id: Mapped[int] = mapped_column(
        ForeignKey("external_flow_boundary_groups.id", ondelete="CASCADE"), primary_key=True
    )
    external_flow_id: Mapped[int] = mapped_column(
        ForeignKey("external_flows.id", ondelete="RESTRICT"), primary_key=True
    )


class ObservedValuationPoint(Base):
    """Owner/provider-captured valuation observation adjacent to an external flow."""

    __tablename__ = "observed_valuation_points"
    __table_args__ = (
        Index(
            "ix_observed_valuation_points_scope_date",
            "scope",
            "account_id",
            "observed_date",
        ),
        Index(
            "ix_observed_valuation_points_flow",
            "external_flow_id",
        ),
        Index(
            "ix_observed_valuation_points_boundary_group",
            "boundary_group_id",
        ),
        CheckConstraint(
            "scope IN ('portfolio', 'account')",
            name="ck_observed_valuation_points_scope",
        ),
        CheckConstraint(
            "(scope = 'portfolio' AND account_id IS NULL) OR "
            "(scope = 'account' AND account_id IS NOT NULL)",
            name="ck_observed_valuation_points_scope_account",
        ),
        CheckConstraint(
            "total_value_kopecks >= 0",
            name="ck_observed_valuation_points_value_nonnegative",
        ),
        CheckConstraint(
            "length(trim(performance_currency)) = 3",
            name="ck_observed_valuation_points_currency_length",
        ),
        CheckConstraint(
            "coverage_status IN ('complete', 'unavailable', 'unknown')",
            name="ck_observed_valuation_points_coverage",
        ),
        CheckConstraint(
            "quality IN ('exact', 'unavailable', 'unknown')",
            name="ck_observed_valuation_points_quality",
        ),
        CheckConstraint(
            "length(trim(provenance_kind)) > 0",
            name="ck_observed_valuation_points_provenance_kind",
        ),
        CheckConstraint(
            "relation IN ('pre_external_flow', 'post_external_flow')",
            name="ck_observed_valuation_points_relation",
        ),
        CheckConstraint(
            "(external_flow_id IS NOT NULL AND boundary_group_id IS NULL) OR "
            "(external_flow_id IS NULL AND boundary_group_id IS NOT NULL)",
            name="ck_observed_valuation_points_single_boundary_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporting_month_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_months.id", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_value_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    performance_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(16), nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    provenance_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    relation: Mapped[str] = mapped_column(String(24), nullable=False)
    external_flow_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_flows.id", ondelete="RESTRICT"), nullable=True
    )
    boundary_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_flow_boundary_groups.id", ondelete="RESTRICT"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def value_kopecks(self) -> int:
        """Compatibility spelling for callers using generic valuation wording."""

        return self.total_value_kopecks


# Public vocabulary aliases keep the implementation discoverable for the
# observed-point and boundary-group terminology used by downstream tasks.
ValuationBoundaryGroup = ExternalFlowBoundaryGroup
ValuationBoundaryGroupMember = ExternalFlowBoundaryGroupMember
ObservedValuationBoundary = ObservedValuationPoint


# Public vocabulary aliases for callers that use the contract's
# ``boundary-flow`` / ``transfer-link`` terminology.
ExternalBoundaryFlow = ExternalFlow
TransferLink = ExternalTransferLink


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


class AppliedProviderPayout(Base):
    """Current owner-accepted provider payout for one month/account/instrument identity."""

    __tablename__ = "applied_provider_payouts"
    __table_args__ = (
        UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "provider",
            "provider_instrument_uid",
            "event_kind",
            "identity_key",
            name="uq_applied_provider_payouts_identity",
        ),
        Index("ix_applied_provider_payouts_month", "reporting_month_id"),
        CheckConstraint(
            "event_kind IN ('coupon', 'dividend', 'redemption')",
            name="ck_applied_provider_payouts_event_kind",
        ),
        CheckConstraint(
            "lifecycle IN ('active', 'cancelled', 'dismissed')",
            name="ck_applied_provider_payouts_lifecycle",
        ),
        CheckConstraint("currency = 'RUB'", name="ck_applied_provider_payouts_currency_rub"),
        CheckConstraint(
            "amount_basis IN ('provider_announced')",
            name="ck_applied_provider_payouts_amount_basis",
        ),
        CheckConstraint("quantity >= 0", name="ck_applied_provider_payouts_quantity_nonnegative"),
        CheckConstraint(
            "total_amount_kopecks >= 0",
            name="ck_applied_provider_payouts_total_nonnegative",
        ),
        CheckConstraint(
            "length(per_unit_amount) > 0",
            name="ck_applied_provider_payouts_per_unit_present",
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
    source_position_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("position_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_instrument_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    per_unit_amount: Mapped[str] = mapped_column(String(64), nullable=False)
    total_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    amount_basis: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="provider_announced",
        server_default=text("'provider_announced'"),
    )
    is_approximate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    provider_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppliedPayoutRevision(Base):
    """Append-only audit of one successful apply/revise/cancel/dismiss."""

    __tablename__ = "applied_payout_revisions"
    __table_args__ = (
        Index("ix_applied_payout_revisions_payout_id", "applied_payout_id"),
        CheckConstraint(
            "revision_kind IN ('apply', 'revise', 'cancel', 'dismiss')",
            name="ck_applied_payout_revisions_kind",
        ),
        CheckConstraint(
            "event_kind IN ('coupon', 'dividend', 'redemption')",
            name="ck_applied_payout_revisions_event_kind",
        ),
        CheckConstraint(
            "lifecycle IN ('active', 'cancelled', 'dismissed')",
            name="ck_applied_payout_revisions_lifecycle",
        ),
        CheckConstraint("currency = 'RUB'", name="ck_applied_payout_revisions_currency_rub"),
        CheckConstraint(
            "amount_basis IN ('provider_announced')",
            name="ck_applied_payout_revisions_amount_basis",
        ),
        CheckConstraint("quantity >= 0", name="ck_applied_payout_revisions_quantity_nonnegative"),
        CheckConstraint(
            "total_amount_kopecks >= 0",
            name="ck_applied_payout_revisions_total_nonnegative",
        ),
        CheckConstraint(
            "length(per_unit_amount) > 0",
            name="ck_applied_payout_revisions_per_unit_present",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_payout_id: Mapped[int] = mapped_column(
        ForeignKey("applied_provider_payouts.id", ondelete="RESTRICT"), nullable=False
    )
    revision_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_position_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("position_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_instrument_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    per_unit_amount: Mapped[str] = mapped_column(String(64), nullable=False)
    total_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    is_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppliedPayoutReconciliation(Base):
    """Explicit 1:1 link from an applied provider payout to one manual expected flow."""

    __tablename__ = "applied_payout_reconciliations"
    __table_args__ = (
        UniqueConstraint(
            "applied_payout_id",
            name="uq_applied_payout_reconciliations_payout",
        ),
        UniqueConstraint(
            "expected_cash_flow_id",
            name="uq_applied_payout_reconciliations_manual_flow",
        ),
        CheckConstraint(
            "counting_decision IN ('keep_both', 'count_manual', 'count_provider')",
            name="ck_applied_payout_reconciliations_decision",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_payout_id: Mapped[int] = mapped_column(
        ForeignKey("applied_provider_payouts.id", ondelete="CASCADE"), nullable=False
    )
    expected_cash_flow_id: Mapped[int] = mapped_column(
        ForeignKey("expected_cash_flows.id", ondelete="CASCADE"), nullable=False
    )
    counting_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class AppliedStatementEvent(Base):
    """Current owner-accepted Alfa depository income-report event.

    At most one *active* row per provider + canonical R06-07 natural identity.
    Retracted rows remain as frozen audit and do not participate in matching.
    Raw PDF bytes, extracted text, provider account refs and beneficiary
    data are never stored here.
    """

    __tablename__ = "applied_statement_events"
    __table_args__ = (
        UniqueConstraint(
            "investment_cash_flow_id",
            name="uq_applied_statement_events_cash_flow",
        ),
        Index("ix_applied_statement_events_account", "account_id"),
        Index(
            "uq_applied_statement_events_active_identity",
            "provider",
            "natural_identity",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "provider IN ('alfa_depository_income_report')",
            name="ck_applied_statement_events_provider",
        ),
        CheckConstraint(
            "event_kind IN ('dividend', 'coupon', 'redemption')",
            name="ck_applied_statement_events_event_kind",
        ),
        CheckConstraint(
            "link_mode IN ('statement_created', 'linked_existing')",
            name="ck_applied_statement_events_link_mode",
        ),
        CheckConstraint(
            "status IN ('active', 'retracted')",
            name="ck_applied_statement_events_status",
        ),
        CheckConstraint(
            "(status = 'active' AND investment_cash_flow_id IS NOT NULL "
            "AND retracted_at IS NULL) OR "
            "(status = 'retracted' AND investment_cash_flow_id IS NULL "
            "AND retracted_at IS NOT NULL)",
            name="ck_applied_statement_events_retract_state",
        ),
        CheckConstraint(
            "length(natural_identity) > 0",
            name="ck_applied_statement_events_identity_present",
        ),
        CheckConstraint(
            "length(material_fingerprint) = 64",
            name="ck_applied_statement_events_fingerprint_sha256",
        ),
        CheckConstraint(
            "length(document_sha256) = 64",
            name="ck_applied_statement_events_document_sha256",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    isin: Mapped[str] = mapped_column(String(12), nullable=False)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    natural_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    material_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    investment_cash_flow_id: Mapped[int | None] = mapped_column(
        ForeignKey("investment_cash_flows.id", ondelete="RESTRICT"), nullable=True
    )
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    link_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppliedStatementEventRevision(Base):
    """Append-only audit of one successful apply, revise, link_existing, or retract."""

    __tablename__ = "applied_statement_event_revisions"
    __table_args__ = (
        Index(
            "ix_applied_statement_event_revisions_event_id",
            "applied_statement_event_id",
        ),
        CheckConstraint(
            "revision_kind IN ('apply', 'revise', 'link_existing', 'retract')",
            name="ck_applied_statement_event_revisions_kind",
        ),
        CheckConstraint(
            "event_kind IN ('dividend', 'coupon', 'redemption')",
            name="ck_applied_statement_event_revisions_event_kind",
        ),
        CheckConstraint(
            "gross_currency = 'RUB'",
            name="ck_applied_statement_event_revisions_gross_currency_rub",
        ),
        CheckConstraint(
            "net_currency = 'RUB'",
            name="ck_applied_statement_event_revisions_net_currency_rub",
        ),
        CheckConstraint(
            "gross_amount_kopecks >= 0",
            name="ck_applied_statement_event_revisions_gross_nonnegative",
        ),
        CheckConstraint(
            "net_amount_kopecks >= 0",
            name="ck_applied_statement_event_revisions_net_nonnegative",
        ),
        CheckConstraint(
            "length(quantity) > 0",
            name="ck_applied_statement_event_revisions_quantity_present",
        ),
        CheckConstraint(
            "length(per_unit) > 0",
            name="ck_applied_statement_event_revisions_per_unit_present",
        ),
        CheckConstraint(
            "(tax_available = 0 AND tax_amount_kopecks IS NULL) OR "
            "(tax_available = 1 AND tax_amount_kopecks IS NOT NULL "
            "AND tax_amount_kopecks >= 0)",
            name="ck_applied_statement_event_revisions_tax_evidence",
        ),
        CheckConstraint(
            "length(natural_identity) > 0",
            name="ck_applied_statement_event_revisions_identity_present",
        ),
        CheckConstraint(
            "length(material_fingerprint) = 64",
            name="ck_applied_statement_event_revisions_fingerprint_sha256",
        ),
        CheckConstraint(
            "length(document_sha256) = 64",
            name="ck_applied_statement_event_revisions_document_sha256",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_statement_event_id: Mapped[int] = mapped_column(
        ForeignKey("applied_statement_events.id", ondelete="RESTRICT"), nullable=False
    )
    revision_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    natural_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    material_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    isin: Mapped[str] = mapped_column(String(12), nullable=False)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[str] = mapped_column(String(64), nullable=False)
    per_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    gross_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tax_amount_kopecks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tax_rate: Mapped[str | None] = mapped_column(String(64), nullable=True)
    net_amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
