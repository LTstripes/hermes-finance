"""Read-only current-state Tax/IIS Planner API (R07-10a / issue #171)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain.salary_tax import TaxBracketRule
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.tax_iis_planner import (
    TAX_IIS_PLANNER_CONTRACT_VERSION,
    IisPlannerAccountSnapshot,
    SalaryTaxPlannerSnapshot,
    TaxIisPlannerSnapshot,
    build_tax_iis_planner,
)

router = APIRouter(prefix="/api/tax-iis-planner", tags=["tax-iis-planner"])

HistoryCoverage = Literal["complete", "unavailable"]


class PlannerReportingMonthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    year: int
    month: int
    status: str
    snapshot_date: date
    source: str


class PlannerTaxBracketOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold_from: MoneyValue
    threshold_to: MoneyValue | None
    rate_bps: int


class PlannerSalaryTaxOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int | None
    history_complete: bool
    history_coverage: HistoryCoverage
    available: bool
    opening_context_available: bool
    taxable_gross_ytd: MoneyValue | None
    current_marginal_bracket: PlannerTaxBracketOut | None
    current_marginal_rate_bps: int | None
    next_threshold: MoneyValue | None
    distance_to_next_threshold: MoneyValue | None
    tax_bracket_source: str | None
    warning_codes: list[str]


class PlannerContributionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int
    amount: MoneyValue
    is_target_reached: bool


class PlannerTaxBenefitTotalsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned: MoneyValue
    submitted: MoneyValue
    received: MoneyValue
    rejected: MoneyValue


class PlannerIisAccountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    account_name: str
    iis_type: str
    opened_at: date
    eligible_close_at: date | None
    contributions_by_tax_year: list[PlannerContributionOut]
    tax_benefits: PlannerTaxBenefitTotalsOut


class PlannerAsOfOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month: PlannerReportingMonthOut | None
    selection_reason: str


class TaxIisPlannerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    tax_year: int | None
    as_of: PlannerAsOfOut
    salary_tax: PlannerSalaryTaxOut
    iis_accounts: list[PlannerIisAccountOut]
    warnings: list[str]


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _money_opt(kopecks: int | None) -> MoneyValue | None:
    return None if kopecks is None else _money(kopecks)


def _bracket_out(bracket: TaxBracketRule | None) -> PlannerTaxBracketOut | None:
    if bracket is None:
        return None
    return PlannerTaxBracketOut(
        threshold_from=_money(bracket.from_kopecks),
        threshold_to=_money_opt(bracket.to_kopecks),
        rate_bps=bracket.rate_bps,
    )


def _salary_tax_out(snapshot: SalaryTaxPlannerSnapshot) -> PlannerSalaryTaxOut:
    bracket = snapshot.current_marginal_bracket
    return PlannerSalaryTaxOut(
        tax_year=snapshot.tax_year,
        history_complete=snapshot.history_complete,
        history_coverage="complete" if snapshot.history_complete else "unavailable",
        available=snapshot.available,
        opening_context_available=snapshot.opening_context_available,
        taxable_gross_ytd=_money_opt(snapshot.taxable_gross_ytd_kopecks),
        current_marginal_bracket=_bracket_out(bracket),
        current_marginal_rate_bps=bracket.rate_bps if bracket is not None else None,
        next_threshold=_money_opt(bracket.to_kopecks if bracket is not None else None),
        distance_to_next_threshold=_money_opt(snapshot.distance_to_next_threshold_kopecks),
        tax_bracket_source=snapshot.tax_bracket_source,
        warning_codes=list(snapshot.warning_codes),
    )


def _iis_account_out(snapshot: IisPlannerAccountSnapshot) -> PlannerIisAccountOut:
    benefits = snapshot.tax_benefits
    return PlannerIisAccountOut(
        account_id=snapshot.account_id,
        account_name=snapshot.account_name,
        iis_type=snapshot.iis_type,
        opened_at=snapshot.opened_at,
        eligible_close_at=snapshot.eligible_close_at,
        contributions_by_tax_year=[
            PlannerContributionOut(
                tax_year=row.tax_year,
                amount=_money(row.amount_kopecks),
                is_target_reached=row.is_target_reached,
            )
            for row in snapshot.contributions
        ],
        tax_benefits=PlannerTaxBenefitTotalsOut(
            planned=_money(benefits.planned_kopecks),
            submitted=_money(benefits.submitted_kopecks),
            received=_money(benefits.received_kopecks),
            rejected=_money(benefits.rejected_kopecks),
        ),
    )


def _reporting_month_out(month: object | None) -> PlannerReportingMonthOut | None:
    if month is None:
        return None
    return PlannerReportingMonthOut(
        id=month.id,
        year=month.year,
        month=month.month,
        status=month.status,
        snapshot_date=month.snapshot_date,
        source=month.source,
    )


def planner_to_out(snapshot: TaxIisPlannerSnapshot) -> TaxIisPlannerOut:
    return TaxIisPlannerOut(
        contract_version=TAX_IIS_PLANNER_CONTRACT_VERSION,
        tax_year=snapshot.tax_year,
        as_of=PlannerAsOfOut(
            reporting_month=_reporting_month_out(snapshot.reporting_month),
            selection_reason=snapshot.selection_reason,
        ),
        salary_tax=_salary_tax_out(snapshot.salary_tax),
        iis_accounts=[_iis_account_out(account) for account in snapshot.iis_accounts],
        warnings=list(snapshot.warnings),
    )


@router.get("", response_model=TaxIisPlannerOut)
def get_tax_iis_planner(
    reporting_month_id: int | None = Query(default=None, gt=0),
    tax_year: int | None = Query(default=None, ge=1900, le=9999),
    account_id: int | None = Query(default=None, gt=0),
    session: Session = Depends(session_for_request),
) -> TaxIisPlannerOut:
    """Return only current persisted tax/IIS context; never mutate or refresh."""
    snapshot = build_tax_iis_planner(
        session,
        reporting_month_id=reporting_month_id,
        tax_year=tax_year,
        account_id=account_id,
    )
    return planner_to_out(snapshot)
