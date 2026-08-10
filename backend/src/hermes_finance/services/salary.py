"""Salary and progressive НДФЛ application service.

Loads SALARY income entries from persistence, maps them to pure-domain
input, calls :func:`calculate_progressive_tax`, and returns the domain
result DTO.  The actual employer-paid net is tracked separately per
MASTER_SPEC §10.14 step 6.

Official progressive scale source:
    https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/
"""

from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import IncomeType, ReportingMonthStatus, RubleAmount
from hermes_finance.domain.salary_tax import (
    SalaryTaxInput,
    SalaryTaxResult,
    TaxBracketRule,
    calculate_progressive_tax,
)
from hermes_finance.persistence import IncomeEntry, ReportingMonth
from hermes_finance.services.reporting_months import get_reporting_month
from hermes_finance.services.salary_tax_context import (
    SalaryTaxHistoryIncompleteError,
    get_salary_tax_year_context,
)
from hermes_finance.services.tax_brackets import get_or_create_default_tax_brackets


def calculate_salary_tax(session: Session, reporting_month_id: int) -> SalaryTaxResult:
    """Calculate progressive НДФЛ for a reporting month's salary payment.

    * ``payment_gross`` = sum of SALARY gross for this reporting month.
    * ``ytd_gross`` follows the opening-context contract: prior months must be
      explicitly closed, and an optional annual opening baseline is used once.
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

    payment_gross = int(payment_gross)
    if payment_gross == 0:
        return SalaryTaxResult(tax_kopecks=0, calculated_net_kopecks=0, parts=())

    context = get_salary_tax_year_context(session, year)
    if month == 1:
        ytd_gross = 0
    else:
        opening_gross = 0
        first_required_month = 1
        if context is not None and month >= context.effective_from_month:
            opening_gross = context.opening_taxable_gross_kopecks
            first_required_month = context.effective_from_month

        known_month_rows = session.execute(
            select(
                ReportingMonth.month,
                func.coalesce(func.sum(IncomeEntry.gross_amount_kopecks), 0),
            )
            .outerjoin(
                IncomeEntry,
                and_(
                    IncomeEntry.reporting_month_id == ReportingMonth.id,
                    IncomeEntry.income_type == IncomeType.SALARY.value,
                ),
            )
            .where(
                ReportingMonth.year == year,
                ReportingMonth.month >= first_required_month,
                ReportingMonth.month < month,
                ReportingMonth.status == ReportingMonthStatus.CLOSED.value,
            )
            .group_by(ReportingMonth.month)
        ).all()
        known_months = {
            int(month_number): int(gross or 0) for month_number, gross in known_month_rows
        }
        required_months = set(range(first_required_month, month))
        missing_months = sorted(required_months - known_months.keys())
        if missing_months:
            raise SalaryTaxHistoryIncompleteError(
                "salary tax history is incomplete before "
                f"{year:04d}-{month:02d}; missing known month(s): "
                + ", ".join(f"{year:04d}-{missing:02d}" for missing in missing_months)
            )
        ytd_gross = opening_gross + sum(known_months.values())

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
