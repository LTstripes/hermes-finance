"""Salary and progressive НДФЛ application service.

Loads SALARY income entries from persistence, maps them to pure-domain
input, calls :func:`calculate_progressive_tax`, and returns the domain
result DTO.  The actual employer-paid net is tracked separately per
MASTER_SPEC §10.14 step 6.

Official progressive scale source:
    https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/
"""

from __future__ import annotations

from dataclasses import dataclass

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
from hermes_finance.services.tax_brackets import (
    effective_tax_bracket_rules,
    get_or_create_default_tax_brackets,
)


@dataclass(frozen=True, slots=True)
class SalaryTaxSnapshot:
    """Read-only salary-tax view for export mapping.

    Completeness and YTD follow the same algorithm as
    :func:`calculate_salary_tax`. Brackets are loaded without seeding.
    """

    tax_year: int
    history_complete: bool
    opening_context_available: bool
    taxable_gross_ytd_kopecks: int | None
    current_marginal_rate_bps: int | None
    warning_codes: tuple[str, ...]
    gross_kopecks: int = 0
    calculated_tax_kopecks: int | None = None
    calculated_net_kopecks: int | None = None
    actual_net_kopecks: int = 0


def _salary_gross_for_month(session: Session, reporting_month_id: int) -> int:
    total = session.execute(
        select(func.coalesce(func.sum(IncomeEntry.gross_amount_kopecks), 0)).where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == IncomeType.SALARY.value,
        )
    ).scalar_one()
    return int(total)


def prior_taxable_gross_ytd(session: Session, reporting_month: ReportingMonth) -> tuple[int, bool]:
    """Return ``(ytd_before_current_payment, opening_context_available)``.

    Prior months must be explicitly closed. An optional annual opening
    baseline is applied once. Raises
    :class:`SalaryTaxHistoryIncompleteError` when required months are
    missing. This is the single completeness/YTD algorithm used by both
    live calculation and the read-only export snapshot.
    """
    year = reporting_month.year
    month = reporting_month.month
    context = get_salary_tax_year_context(session, year)
    opening_available = context is not None
    if month == 1:
        return 0, opening_available

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
    known_months = {int(month_number): int(gross or 0) for month_number, gross in known_month_rows}
    required_months = set(range(first_required_month, month))
    missing_months = sorted(required_months - known_months.keys())
    if missing_months:
        raise SalaryTaxHistoryIncompleteError(
            "salary tax history is incomplete before "
            f"{year:04d}-{month:02d}; missing known month(s): "
            + ", ".join(f"{year:04d}-{missing:02d}" for missing in missing_months)
        )
    return opening_gross + sum(known_months.values()), opening_available


def _progressive_tax(
    session: Session,
    *,
    year: int,
    ytd_gross_kopecks: int,
    payment_gross_kopecks: int,
    seed_brackets: bool,
) -> SalaryTaxResult:
    if payment_gross_kopecks == 0:
        return SalaryTaxResult(tax_kopecks=0, calculated_net_kopecks=0, parts=())
    if seed_brackets:
        brackets_orm = get_or_create_default_tax_brackets(session, year)
        brackets = tuple(
            TaxBracketRule(
                from_kopecks=item.threshold_from_kopecks,
                to_kopecks=item.threshold_to_kopecks,
                rate_bps=item.rate_bps,
            )
            for item in brackets_orm
        )
    else:
        brackets = effective_tax_bracket_rules(session, year)
    return calculate_progressive_tax(
        SalaryTaxInput(
            ytd_gross_kopecks=ytd_gross_kopecks,
            payment_gross_kopecks=payment_gross_kopecks,
            brackets=brackets,
        )
    )


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
    payment_gross = _salary_gross_for_month(session, reporting_month_id)
    if payment_gross == 0:
        return SalaryTaxResult(tax_kopecks=0, calculated_net_kopecks=0, parts=())
    ytd_gross, _opening = prior_taxable_gross_ytd(session, reporting_month)
    return _progressive_tax(
        session,
        year=reporting_month.year,
        ytd_gross_kopecks=ytd_gross,
        payment_gross_kopecks=payment_gross,
        seed_brackets=True,
    )


def salary_tax_snapshot_for_month(session: Session, reporting_month_id: int) -> SalaryTaxSnapshot:
    """Read-only salary-tax snapshot for the AI analysis bundle exporter.

    Does not INSERT/UPDATE/DELETE. Maps incomplete history to an unavailable
    state instead of assuming zero. Uses in-memory official defaults when no
    brackets are persisted for the year.
    """
    reporting_month = get_reporting_month(session, reporting_month_id)
    opening_available = get_salary_tax_year_context(session, reporting_month.year) is not None
    try:
        ytd_before, opening_available = prior_taxable_gross_ytd(session, reporting_month)
    except SalaryTaxHistoryIncompleteError:
        gross = _salary_gross_for_month(session, reporting_month_id)
        return SalaryTaxSnapshot(
            tax_year=reporting_month.year,
            history_complete=False,
            opening_context_available=opening_available,
            taxable_gross_ytd_kopecks=None,
            current_marginal_rate_bps=None,
            warning_codes=("salary_tax_history_incomplete",),
            gross_kopecks=gross,
            actual_net_kopecks=actual_net_for_month(session, reporting_month_id).kopecks,
        )
    payment_gross = _salary_gross_for_month(session, reporting_month_id)
    result = _progressive_tax(
        session,
        year=reporting_month.year,
        ytd_gross_kopecks=ytd_before,
        payment_gross_kopecks=payment_gross,
        seed_brackets=False,
    )
    marginal_bps: int | None = None
    for part in result.parts:
        if part.taxable_kopecks > 0:
            marginal_bps = part.rate_bps
    return SalaryTaxSnapshot(
        tax_year=reporting_month.year,
        history_complete=True,
        opening_context_available=opening_available,
        taxable_gross_ytd_kopecks=ytd_before + payment_gross,
        current_marginal_rate_bps=marginal_bps,
        warning_codes=(),
        gross_kopecks=payment_gross,
        calculated_tax_kopecks=result.tax_kopecks,
        calculated_net_kopecks=result.calculated_net_kopecks,
        actual_net_kopecks=actual_net_for_month(session, reporting_month_id).kopecks,
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
