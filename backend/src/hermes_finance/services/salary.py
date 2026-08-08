"""Salary and progressive НДФЛ application service.

Loads SALARY income entries from persistence, maps them to pure-domain
input, calls :func:`calculate_progressive_tax`, and returns the domain
result DTO.  The actual employer-paid net is tracked separately per
MASTER_SPEC §10.14 step 6.

Official progressive scale source:
    https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import IncomeType, RubleAmount
from hermes_finance.domain.salary_tax import (
    SalaryTaxInput,
    SalaryTaxResult,
    TaxBracketRule,
    calculate_progressive_tax,
)
from hermes_finance.persistence import IncomeEntry, ReportingMonth
from hermes_finance.services.reporting_months import get_reporting_month
from hermes_finance.services.tax_brackets import get_or_create_default_tax_brackets


def calculate_salary_tax(session: Session, reporting_month_id: int) -> SalaryTaxResult:
    """Calculate progressive НДФЛ for a reporting month's salary payment.

    * ``payment_gross`` = sum of SALARY gross for this reporting month.
    * ``ytd_gross`` = sum of SALARY gross in strictly earlier reporting
      months of the same calendar year.
    * Brackets are loaded (or seeded) from the tax-brackets configuration
      table for the reporting month's year.

    Returns the pure-domain :class:`SalaryTaxResult`.
    """
    reporting_month = get_reporting_month(session, reporting_month_id)
    year = reporting_month.year
    month = reporting_month.month

    payment_gross = session.execute(
        select(func.coalesce(func.sum(IncomeEntry.gross_amount_kopecks), 0)).where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == IncomeType.SALARY.value,
        )
    ).scalar_one()

    ytd_gross = session.execute(
        select(func.coalesce(func.sum(IncomeEntry.gross_amount_kopecks), 0))
        .join(ReportingMonth, IncomeEntry.reporting_month_id == ReportingMonth.id)
        .where(
            ReportingMonth.year == year,
            ReportingMonth.month < month,
            IncomeEntry.income_type == IncomeType.SALARY.value,
        )
    ).scalar_one()

    brackets_orm = get_or_create_default_tax_brackets(session, year)
    brackets = tuple(
        TaxBracketRule(
            from_kopecks=b.threshold_from_kopecks,
            to_kopecks=b.threshold_to_kopecks,
            rate_bps=b.rate_bps,
        )
        for b in brackets_orm
    )

    return calculate_progressive_tax(
        SalaryTaxInput(
            ytd_gross_kopecks=ytd_gross,
            payment_gross_kopecks=payment_gross,
            brackets=brackets,
        )
    )


def actual_net_for_month(session: Session, reporting_month_id: int) -> RubleAmount:
    """Return the actual (employer-paid) SALARY net for the month.

    This is the sum of ``net_amount_kopecks`` for SALARY entries of the given
    reporting month.  Per MASTER_SPEC §10.14 step 6, the actual net is kept
    separate from the calculated net, because the employer payment may differ
    due to deductions and recalculations.
    """
    total = session.execute(
        select(func.coalesce(func.sum(IncomeEntry.net_amount_kopecks), 0)).where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == IncomeType.SALARY.value,
        )
    ).scalar_one()
    return RubleAmount(total)
