from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.domain.salary_tax import TaxBracketRule
from hermes_finance.services.tax_brackets import (
    TAX_BRACKETS_CONTRACT_VERSION,
    TAX_BRACKETS_SOURCE_MANUAL,
    TAX_BRACKETS_SOURCE_OFFICIAL,
    closed_month_numbers_for_tax_year,
    effective_tax_bracket_rules,
    replace_tax_brackets_for_year,
    tax_bracket_source,
)

router = APIRouter(prefix="/api/tax-brackets", tags=["tax-brackets"])

TaxBracketSource = Literal["official_default", "manual_configuration"]


class TaxBracketRulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold_from: MoneyValue
    threshold_to: MoneyValue | None = None
    rate_bps: int = Field(ge=0, le=10_000)


class TaxBracketYearUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brackets: list[TaxBracketRulePayload] = Field(min_length=1)


class TaxBracketRuleResponse(BaseModel):
    threshold_from: MoneyValue
    threshold_to: MoneyValue | None
    rate_bps: int


class TaxBracketYearResponse(BaseModel):
    year: int
    effective_from: date
    effective_to: date
    source: TaxBracketSource
    contract_version: str
    mutable: bool
    closed_months: list[str]
    brackets: list[TaxBracketRuleResponse]


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _response(session: Session, year: int) -> TaxBracketYearResponse:
    rules = effective_tax_bracket_rules(session, year)
    closed_months = closed_month_numbers_for_tax_year(session, year)
    source = tax_bracket_source(rules)
    return TaxBracketYearResponse(
        year=year,
        effective_from=date(year, 1, 1),
        effective_to=date(year, 12, 31),
        source=(
            TAX_BRACKETS_SOURCE_OFFICIAL
            if source == TAX_BRACKETS_SOURCE_OFFICIAL
            else TAX_BRACKETS_SOURCE_MANUAL
        ),
        contract_version=TAX_BRACKETS_CONTRACT_VERSION,
        mutable=not closed_months,
        closed_months=[f"{year:04d}-{month:02d}" for month in closed_months],
        brackets=[
            TaxBracketRuleResponse(
                threshold_from=_money(rule.from_kopecks),
                threshold_to=_money(rule.to_kopecks) if rule.to_kopecks is not None else None,
                rate_bps=rule.rate_bps,
            )
            for rule in rules
        ],
    )


@router.get("/{year}", response_model=TaxBracketYearResponse)
def read_tax_brackets(
    year: int = Path(ge=2000, le=2100),
    session: Session = Depends(session_for_request),
) -> TaxBracketYearResponse:
    return _response(session, year)


@router.put("/{year}", response_model=TaxBracketYearResponse)
def write_tax_brackets(
    payload: TaxBracketYearUpdate,
    year: int = Path(ge=2000, le=2100),
    session: Session = Depends(session_for_request),
) -> TaxBracketYearResponse:
    rules = tuple(
        TaxBracketRule(
            from_kopecks=RubleAmount.from_api(item.threshold_from.amount).kopecks,
            to_kopecks=(
                RubleAmount.from_api(item.threshold_to.amount).kopecks
                if item.threshold_to is not None
                else None
            ),
            rate_bps=item.rate_bps,
        )
        for item in payload.brackets
    )
    replace_tax_brackets_for_year(session, year, rules)
    return _response(session, year)
