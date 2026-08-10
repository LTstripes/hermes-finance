"""Persistence service for annual opening salary-tax YTD contexts (R02-03)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import SalaryTaxYearContext

_MIN_TAX_YEAR = 1
_MAX_TAX_YEAR = 9999


class SalaryTaxHistoryIncompleteError(ValueError):
    """Salary tax cannot be calculated without a complete known-month history."""

    code = "salary_tax_history_incomplete"


def _require_tax_year(tax_year: int) -> int:
    if isinstance(tax_year, bool) or not isinstance(tax_year, int):
        raise TypeError("tax_year must be an int")
    if not _MIN_TAX_YEAR <= tax_year <= _MAX_TAX_YEAR:
        raise ValueError("tax_year must be between 1 and 9999")
    return tax_year


def _require_month(month: int) -> int:
    if isinstance(month, bool) or not isinstance(month, int):
        raise TypeError("effective_from_month must be an int")
    if not 1 <= month <= 12:
        raise ValueError("effective_from_month must be between 1 and 12")
    return month


def _opening_kopecks(value: str | RubleAmount) -> int:
    amount = value if isinstance(value, RubleAmount) else RubleAmount.from_api(value)
    if amount.kopecks < 0:
        raise ValueError("opening taxable gross must not be negative")
    return amount.kopecks


def _validate_values(
    *, tax_year: int, effective_from_month: int, opening_taxable_gross: str | RubleAmount
) -> tuple[int, int, int]:
    normalized_year = _require_tax_year(tax_year)
    normalized_month = _require_month(effective_from_month)
    opening_kopecks = _opening_kopecks(opening_taxable_gross)
    if normalized_month == 1 and opening_kopecks != 0:
        raise ValueError("opening taxable gross must be zero when effective_from_month is 1")
    return normalized_year, normalized_month, opening_kopecks


def get_salary_tax_year_context(session: Session, tax_year: int) -> SalaryTaxYearContext | None:
    return session.get(SalaryTaxYearContext, _require_tax_year(tax_year))


def upsert_salary_tax_year_context(
    session: Session,
    *,
    tax_year: int,
    effective_from_month: int,
    opening_taxable_gross: str | RubleAmount,
) -> SalaryTaxYearContext:
    """Create or replace the single opening context for a calendar year."""
    normalized_year, normalized_month, opening_kopecks = _validate_values(
        tax_year=tax_year,
        effective_from_month=effective_from_month,
        opening_taxable_gross=opening_taxable_gross,
    )
    context = session.get(SalaryTaxYearContext, normalized_year)
    if context is None:
        context = SalaryTaxYearContext(tax_year=normalized_year)
        session.add(context)
    context.effective_from_month = normalized_month
    context.opening_taxable_gross_kopecks = opening_kopecks
    session.commit()
    session.refresh(context)
    return context


def delete_salary_tax_year_context(session: Session, tax_year: int) -> None:
    """Delete the opening context if present; repeated DELETE is idempotent."""
    context = get_salary_tax_year_context(session, tax_year)
    if context is not None:
        session.delete(context)
        session.commit()
