from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
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
