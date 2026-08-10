"""Load the local, untracked private seed into a local database."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import Database
from hermes_finance.domain import AccountStatus, AccountType, RubleAmount
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    DEFAULT_BASE_CURRENCY,
    DEFAULT_FORMULA_VERSION,
    DEFAULT_LOCALE,
    DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
    DEFAULT_TIMEZONE,
    Account,
    AppSettings,
    SalaryTaxYearContext,
)

DEFAULT_PRIVATE_SEED_FILENAME = "private_seed.json"


class _SeedMoney(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(min_length=1)
    currency: Literal["RUB"]

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        amount = RubleAmount.from_api(value)
        if amount.kopecks < 0:
            raise ValueError("amount must not be negative")
        return value


class _SeedSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_currency: Literal["RUB"]
    locale: str = Field(min_length=2, max_length=32)
    timezone: str = Field(min_length=1, max_length=64)
    passive_income_goal: _SeedMoney
    formula_version: str = Field(min_length=1, max_length=32)


class _SeedAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    account_type: AccountType
    external_code: str = Field(min_length=1, max_length=128)
    status: AccountStatus = AccountStatus.ACTIVE
    include_in_capital: bool = True
    include_in_returns: bool = True
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "external_code")
    @classmethod
    def normalize_key_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("account key fields must not be empty")
        return normalized


class _SeedSalaryTaxOpeningContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(ge=1, le=9999)
    effective_from_month: int = Field(ge=1, le=12)
    opening_taxable_gross: str = Field(min_length=1)

    @field_validator("opening_taxable_gross")
    @classmethod
    def validate_opening_gross(cls, value: str) -> str:
        amount = RubleAmount.from_api(value)
        if amount.kopecks < 0:
            raise ValueError("opening taxable gross must not be negative")
        return value


class _PrivateSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    schema_version: Literal[1]
    settings: _SeedSettings
    accounts: list[_SeedAccount]
    salary_tax_opening_contexts: list[_SeedSalaryTaxOpeningContext] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PrivateSeedLoadResult:
    accounts_created: int
    accounts_updated: int
    settings_updated: bool


def _parse_seed(path: Path) -> _PrivateSeed:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("private seed file is not available") from error

    try:
        payload = json.loads(raw)
        seed = _PrivateSeed.model_validate(payload)
    except (JSONDecodeError, TypeError, ValidationError) as error:
        raise ValueError("private seed validation failed") from error

    external_codes = [account.external_code for account in seed.accounts]
    if len(external_codes) != len(set(external_codes)):
        raise ValueError("private seed contains duplicate account keys")
    tax_years = [context.tax_year for context in seed.salary_tax_opening_contexts]
    if len(tax_years) != len(set(tax_years)):
        raise ValueError("private seed contains duplicate salary tax years")
    return seed


def _settings_from_seed(session: Session, seed: _PrivateSeed) -> AppSettings:
    settings = session.get(AppSettings, APP_SETTINGS_ID)
    if settings is None:
        settings = AppSettings(
            id=APP_SETTINGS_ID,
            base_currency=DEFAULT_BASE_CURRENCY,
            locale=DEFAULT_LOCALE,
            timezone=DEFAULT_TIMEZONE,
            passive_income_goal_kopecks=DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
            formula_version=DEFAULT_FORMULA_VERSION,
        )
        session.add(settings)

    settings.base_currency = seed.settings.base_currency
    settings.locale = seed.settings.locale
    settings.timezone = seed.settings.timezone
    settings.passive_income_goal_kopecks = RubleAmount.from_api(
        seed.settings.passive_income_goal.amount
    ).kopecks
    settings.formula_version = seed.settings.formula_version
    return settings


def _upsert_accounts(session: Session, seed: _PrivateSeed) -> tuple[int, int]:
    created = 0
    updated = 0
    for item in seed.accounts:
        account = session.scalar(select(Account).where(Account.external_code == item.external_code))
        if account is None:
            account = Account(external_code=item.external_code)
            session.add(account)
            created += 1
        else:
            updated += 1

        account.name = item.name.strip()
        account.account_type = item.account_type.value
        account.status = item.status.value
        account.include_in_capital = item.include_in_capital
        account.include_in_returns = item.include_in_returns
        account.notes = item.notes
    return created, updated


def _upsert_salary_tax_contexts(session: Session, seed: _PrivateSeed) -> None:
    for item in seed.salary_tax_opening_contexts:
        opening_kopecks = RubleAmount.from_api(item.opening_taxable_gross).kopecks
        if item.effective_from_month == 1 and opening_kopecks != 0:
            raise ValueError("opening taxable gross must be zero when effective_from_month is 1")

        context = session.get(SalaryTaxYearContext, item.tax_year)
        if context is None:
            context = SalaryTaxYearContext(tax_year=item.tax_year)
            session.add(context)
        context.effective_from_month = item.effective_from_month
        context.opening_taxable_gross_kopecks = opening_kopecks


def load_private_seed(database: Database, seed_path: Path | None = None) -> PrivateSeedLoadResult:
    """Validate and idempotently apply the local private seed in one transaction."""
    path = seed_path or database.database_path.parent / DEFAULT_PRIVATE_SEED_FILENAME
    seed = _parse_seed(path)

    with database.session_factory() as session:
        try:
            _settings_from_seed(session, seed)
            accounts_created, accounts_updated = _upsert_accounts(session, seed)
            _upsert_salary_tax_contexts(session, seed)
            session.commit()
        except Exception:
            session.rollback()
            raise

    return PrivateSeedLoadResult(
        accounts_created=accounts_created,
        accounts_updated=accounts_updated,
        settings_updated=True,
    )
