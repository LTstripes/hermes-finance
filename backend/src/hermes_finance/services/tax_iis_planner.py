"""Read-only current-state Tax/IIS Planner assembler.

This service deliberately composes existing persisted Hermes data and
authoritative salary-tax services.  It does not project year-end salary,
extrapolate recurring income, calculate securities tax, or call a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import ReportingMonthStatus, TaxBenefitStatus
from hermes_finance.domain.salary_tax import TaxBracketRule
from hermes_finance.domain.tax_iis_planner import tax_bracket_position
from hermes_finance.persistence import Account, IisProfile, ReportingMonth
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.iis import (
    get_iis_profile_by_account,
    list_iis_contributions,
    list_tax_benefits,
)
from hermes_finance.services.salary import salary_tax_snapshot_for_month
from hermes_finance.services.tax_brackets import (
    effective_tax_bracket_rules,
    tax_bracket_source,
    validate_complete_tax_bracket_rules,
)

TAX_IIS_PLANNER_CONTRACT_VERSION = "tax_iis_planner_v1"
SALARY_TAX_HISTORY_INCOMPLETE = "salary_tax_history_incomplete"
SALARY_TAX_CONTEXT_UNAVAILABLE = "salary_tax_context_unavailable"
TAX_BRACKETS_UNAVAILABLE = "tax_brackets_unavailable"


@dataclass(frozen=True, slots=True)
class SalaryTaxPlannerSnapshot:
    """Current salary-tax context without any future projection."""

    tax_year: int | None
    history_complete: bool
    available: bool
    opening_context_available: bool
    taxable_gross_ytd_kopecks: int | None
    current_marginal_bracket: TaxBracketRule | None
    distance_to_next_threshold_kopecks: int | None
    tax_bracket_source: str | None
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IisContributionPlannerSnapshot:
    """Persisted contribution row used by the planner."""

    tax_year: int
    amount_kopecks: int
    is_target_reached: bool


@dataclass(frozen=True, slots=True)
class IisTaxBenefitTotals:
    """Persisted benefits grouped by status; statuses are never combined."""

    planned_kopecks: int
    submitted_kopecks: int
    received_kopecks: int
    rejected_kopecks: int


@dataclass(frozen=True, slots=True)
class IisPlannerAccountSnapshot:
    """Persisted IIS profile and contribution/benefit status summary."""

    account_id: int
    account_name: str
    iis_type: str
    opened_at: date
    eligible_close_at: date | None
    contributions: tuple[IisContributionPlannerSnapshot, ...]
    tax_benefits: IisTaxBenefitTotals


@dataclass(frozen=True, slots=True)
class TaxIisPlannerSnapshot:
    """Read-only planner payload assembled from local persisted data."""

    tax_year: int | None
    reporting_month: ReportingMonth | None
    selection_reason: str
    salary_tax: SalaryTaxPlannerSnapshot
    iis_accounts: tuple[IisPlannerAccountSnapshot, ...]
    warnings: tuple[str, ...]


def _latest_month(
    session: Session,
    *,
    tax_year: int | None = None,
    closed_only: bool = False,
) -> ReportingMonth | None:
    statement = select(ReportingMonth)
    if tax_year is not None:
        statement = statement.where(ReportingMonth.year == tax_year)
    if closed_only:
        statement = statement.where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
    statement = statement.order_by(
        ReportingMonth.year.desc(),
        ReportingMonth.month.desc(),
        ReportingMonth.id.desc(),
    )
    return session.scalar(statement.limit(1))


def _select_reporting_month(
    session: Session,
    *,
    reporting_month_id: int | None,
    tax_year: int | None,
) -> tuple[ReportingMonth | None, str]:
    if reporting_month_id is not None:
        month = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise LookupError(f"reporting month {reporting_month_id} was not found")
        if tax_year is not None and month.year != tax_year:
            raise ValueError("reporting_month_id and tax_year must refer to the same year")
        return month, "requested"

    if tax_year is not None:
        month = _latest_month(session, tax_year=tax_year, closed_only=True)
        if month is not None:
            return month, "latest_closed"
        return _latest_month(session, tax_year=tax_year), "latest_available"

    month = _latest_month(session, closed_only=True)
    if month is not None:
        return month, "latest_closed"
    return _latest_month(session), "latest_available"


def _salary_tax_context(
    session: Session,
    reporting_month: ReportingMonth | None,
    tax_year: int | None,
) -> SalaryTaxPlannerSnapshot:
    if reporting_month is None:
        return SalaryTaxPlannerSnapshot(
            tax_year=tax_year,
            history_complete=False,
            available=False,
            opening_context_available=False,
            taxable_gross_ytd_kopecks=None,
            current_marginal_bracket=None,
            distance_to_next_threshold_kopecks=None,
            tax_bracket_source=None,
            warning_codes=(SALARY_TAX_CONTEXT_UNAVAILABLE,),
        )

    rules = effective_tax_bracket_rules(session, reporting_month.year)
    source = tax_bracket_source(rules)
    try:
        snapshot = salary_tax_snapshot_for_month(session, reporting_month.id)
    except ValueError:
        return SalaryTaxPlannerSnapshot(
            tax_year=reporting_month.year,
            history_complete=True,
            available=False,
            opening_context_available=False,
            taxable_gross_ytd_kopecks=None,
            current_marginal_bracket=None,
            distance_to_next_threshold_kopecks=None,
            tax_bracket_source=source,
            warning_codes=(TAX_BRACKETS_UNAVAILABLE,),
        )
    if not snapshot.history_complete:
        warning_codes = tuple(sorted(set(snapshot.warning_codes) | {SALARY_TAX_HISTORY_INCOMPLETE}))
        return SalaryTaxPlannerSnapshot(
            tax_year=snapshot.tax_year,
            history_complete=False,
            available=False,
            opening_context_available=snapshot.opening_context_available,
            taxable_gross_ytd_kopecks=None,
            current_marginal_bracket=None,
            distance_to_next_threshold_kopecks=None,
            tax_bracket_source=source,
            warning_codes=warning_codes,
        )

    try:
        complete_rules = validate_complete_tax_bracket_rules(rules)
        if snapshot.taxable_gross_ytd_kopecks is None:
            raise ValueError("salary-tax snapshot has no taxable gross YTD")
        position = tax_bracket_position(complete_rules, snapshot.taxable_gross_ytd_kopecks)
    except ValueError:
        return SalaryTaxPlannerSnapshot(
            tax_year=snapshot.tax_year,
            history_complete=True,
            available=False,
            opening_context_available=snapshot.opening_context_available,
            taxable_gross_ytd_kopecks=snapshot.taxable_gross_ytd_kopecks,
            current_marginal_bracket=None,
            distance_to_next_threshold_kopecks=None,
            tax_bracket_source=source,
            warning_codes=(TAX_BRACKETS_UNAVAILABLE,),
        )

    return SalaryTaxPlannerSnapshot(
        tax_year=snapshot.tax_year,
        history_complete=True,
        available=True,
        opening_context_available=snapshot.opening_context_available,
        taxable_gross_ytd_kopecks=snapshot.taxable_gross_ytd_kopecks,
        current_marginal_bracket=position.bracket,
        distance_to_next_threshold_kopecks=position.distance_to_next_threshold_kopecks,
        tax_bracket_source=source,
        warning_codes=(),
    )


def _iis_accounts(
    session: Session,
    account_id: int | None,
) -> tuple[IisPlannerAccountSnapshot, ...]:
    if account_id is not None:
        account = session.get(Account, account_id)
        if account is None:
            raise AccountNotFoundError(f"account {account_id} was not found")
        profile = get_iis_profile_by_account(session, account_id)
        if profile is None:
            raise ValueError(f"account {account_id} is not an IIS account")
        profile_rows = [(account, profile)]
    else:
        profile_rows = list(
            session.execute(
                select(Account, IisProfile)
                .join(IisProfile, IisProfile.account_id == Account.id)
                .order_by(Account.name, Account.id)
            ).all()
        )

    result: list[IisPlannerAccountSnapshot] = []
    for account, profile in profile_rows:
        contributions = tuple(
            IisContributionPlannerSnapshot(
                tax_year=row.tax_year,
                amount_kopecks=row.amount_kopecks,
                is_target_reached=row.is_target_reached,
            )
            for row in list_iis_contributions(session, account.id)
        )
        totals = {status.value: 0 for status in TaxBenefitStatus}
        for benefit in list_tax_benefits(session, account.id):
            if benefit.status in totals:
                totals[benefit.status] += benefit.amount_kopecks

        result.append(
            IisPlannerAccountSnapshot(
                account_id=account.id,
                account_name=account.name,
                iis_type=profile.iis_type,
                opened_at=profile.opened_at,
                eligible_close_at=profile.eligible_close_at,
                contributions=contributions,
                tax_benefits=IisTaxBenefitTotals(
                    planned_kopecks=totals[TaxBenefitStatus.PLANNED.value],
                    submitted_kopecks=totals[TaxBenefitStatus.SUBMITTED.value],
                    received_kopecks=totals[TaxBenefitStatus.RECEIVED.value],
                    rejected_kopecks=totals[TaxBenefitStatus.REJECTED.value],
                ),
            )
        )
    return tuple(result)


def build_tax_iis_planner(
    session: Session,
    *,
    reporting_month_id: int | None = None,
    tax_year: int | None = None,
    account_id: int | None = None,
) -> TaxIisPlannerSnapshot:
    """Build a bounded current-state planner payload.

    The selected month is only an as-of anchor for the persisted salary-tax
    snapshot.  No future months or recurring salary rows are synthesized.
    """
    reporting_month, selection_reason = _select_reporting_month(
        session,
        reporting_month_id=reporting_month_id,
        tax_year=tax_year,
    )
    selected_tax_year = reporting_month.year if reporting_month is not None else tax_year
    salary_tax = _salary_tax_context(session, reporting_month, selected_tax_year)
    iis_accounts = _iis_accounts(session, account_id)
    return TaxIisPlannerSnapshot(
        tax_year=selected_tax_year,
        reporting_month=reporting_month,
        selection_reason=selection_reason,
        salary_tax=salary_tax,
        iis_accounts=iis_accounts,
        warnings=salary_tax.warning_codes,
    )
