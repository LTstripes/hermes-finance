"""Salary-tax opening YTD context API (R02-03)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import SalaryTaxYearContext
from hermes_finance.services.salary_tax_context import (
    delete_salary_tax_year_context,
    get_salary_tax_year_context,
    upsert_salary_tax_year_context,
)

router = APIRouter(prefix="/api/salary-tax", tags=["salary-tax"])


class SalaryTaxOpeningContextUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from_month: int = Field(ge=1, le=12)
    opening_taxable_gross: MoneyValue


class SalaryTaxOpeningContextResponse(BaseModel):
    tax_year: int
    effective_from_month: int
    opening_taxable_gross: MoneyValue


def _response(context: SalaryTaxYearContext) -> SalaryTaxOpeningContextResponse:
    return SalaryTaxOpeningContextResponse(
        tax_year=context.tax_year,
        effective_from_month=context.effective_from_month,
        opening_taxable_gross=MoneyValue(
            amount=RubleAmount(context.opening_taxable_gross_kopecks).to_api(),
            currency="RUB",
        ),
    )


@router.get(
    "/years/{tax_year}/opening-context",
    response_model=SalaryTaxOpeningContextResponse,
)
def get_opening_context(
    tax_year: int = Path(..., ge=1, le=9999),
    session: Session = Depends(session_for_request),
) -> SalaryTaxOpeningContextResponse:
    context = get_salary_tax_year_context(session, tax_year)
    if context is None:
        raise LookupError(f"salary tax opening context for {tax_year} was not found")
    return _response(context)


@router.put(
    "/years/{tax_year}/opening-context",
    response_model=SalaryTaxOpeningContextResponse,
)
def put_opening_context(
    payload: SalaryTaxOpeningContextUpsert,
    tax_year: int = Path(..., ge=1, le=9999),
    session: Session = Depends(session_for_request),
) -> SalaryTaxOpeningContextResponse:
    context = upsert_salary_tax_year_context(
        session,
        tax_year=tax_year,
        effective_from_month=payload.effective_from_month,
        opening_taxable_gross=RubleAmount.from_api(payload.opening_taxable_gross.amount),
    )
    return _response(context)


@router.delete(
    "/years/{tax_year}/opening-context",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_opening_context(
    tax_year: int = Path(..., ge=1, le=9999),
    session: Session = Depends(session_for_request),
) -> None:
    delete_salary_tax_year_context(session, tax_year)
