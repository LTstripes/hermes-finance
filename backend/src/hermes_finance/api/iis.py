"""IIS API (D04).

Account-scoped CRUD for IIS profile, contributions, and tax benefits.
All endpoints are under ``/api/iis/{account_id}/...``.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount, TaxBenefitStatus
from hermes_finance.persistence import Account
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.iis import (
    create_iis_contribution,
    create_iis_profile,
    create_tax_benefit,
    delete_iis_contribution,
    delete_iis_profile,
    delete_tax_benefit,
    get_iis_contribution_by_key,
    get_iis_profile_by_account,
    get_tax_benefit_by_key,
    list_iis_contributions,
    list_tax_benefits,
    update_iis_contribution,
    update_iis_profile,
    update_tax_benefit,
)

router = APIRouter(prefix="/api/iis", tags=["iis"])


# --- Pydantic models ---


class IisProfileUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iis_type: str = Field(min_length=1, max_length=32)
    opened_at: date
    eligible_close_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class IisProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iis_type: str | None = Field(default=None, min_length=1, max_length=32)
    opened_at: date | None = None
    eligible_close_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class IisProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    iis_type: str
    opened_at: date
    eligible_close_at: date | None
    notes: str | None


class IisContributionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(ge=1900, le=9999)
    amount: MoneyValue
    is_target_reached: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class IisContributionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int | None = Field(default=None, ge=1900, le=9999)
    amount: MoneyValue | None = None
    is_target_reached: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class IisContributionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    tax_year: int
    amount: MoneyValue
    is_target_reached: bool
    notes: str | None


class TaxBenefitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(ge=1900, le=9999)
    benefit_type: str = Field(min_length=1, max_length=32)
    status: str = Field(min_length=1, max_length=16)
    amount: MoneyValue
    received_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class TaxBenefitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int | None = Field(default=None, ge=1900, le=9999)
    benefit_type: str | None = Field(default=None, min_length=1, max_length=32)
    status: str | None = Field(default=None, min_length=1, max_length=16)
    amount: MoneyValue | None = None
    received_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class TaxBenefitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    tax_year: int
    benefit_type: str
    status: str
    amount: MoneyValue
    received_at: date | None
    notes: str | None


# --- helpers ---


def _require_account(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")


def _validate_tax_benefit_status(value: str) -> str:
    try:
        TaxBenefitStatus(value)
    except ValueError as error:
        raise ValueError(f"unsupported tax benefit status: {value!r}") from error
    return value


def _profile_response(profile: object) -> IisProfileResponse:
    return IisProfileResponse(
        id=profile.id,
        account_id=profile.account_id,
        iis_type=profile.iis_type,
        opened_at=profile.opened_at,
        eligible_close_at=profile.eligible_close_at,
        notes=profile.notes,
    )


def _contribution_response(contribution: object) -> IisContributionResponse:
    return IisContributionResponse(
        id=contribution.id,
        account_id=contribution.account_id,
        tax_year=contribution.tax_year,
        amount=MoneyValue(
            amount=RubleAmount(contribution.amount_kopecks).to_api(),
            currency="RUB",
        ),
        is_target_reached=contribution.is_target_reached,
        notes=contribution.notes,
    )


def _benefit_response(benefit: object) -> TaxBenefitResponse:
    return TaxBenefitResponse(
        id=benefit.id,
        account_id=benefit.account_id,
        tax_year=benefit.tax_year,
        benefit_type=benefit.benefit_type,
        status=benefit.status,
        amount=MoneyValue(
            amount=RubleAmount(benefit.amount_kopecks).to_api(),
            currency="RUB",
        ),
        received_at=benefit.received_at,
        notes=benefit.notes,
    )


def _amount_from_money(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


# --- profile endpoints ---


@router.get("/{account_id}/profile", response_model=IisProfileResponse)
def get_iis_profile_endpoint(
    account_id: int,
    session: Session = Depends(session_for_request),
) -> IisProfileResponse:
    _require_account(session, account_id)
    profile = get_iis_profile_by_account(session, account_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IIS profile for account {account_id} was not found",
        )
    return _profile_response(profile)


@router.put("/{account_id}/profile", response_model=IisProfileResponse)
def upsert_iis_profile_endpoint(
    account_id: int,
    payload: IisProfileUpsert,
    session: Session = Depends(session_for_request),
) -> IisProfileResponse:
    _require_account(session, account_id)
    existing = get_iis_profile_by_account(session, account_id)
    if existing is not None:
        profile = update_iis_profile(
            session,
            account_id=account_id,
            iis_type=payload.iis_type,
            opened_at=payload.opened_at,
            eligible_close_at=payload.eligible_close_at,
            notes=payload.notes,
        )
    else:
        profile = create_iis_profile(
            session,
            account_id=account_id,
            iis_type=payload.iis_type,
            opened_at=payload.opened_at,
            eligible_close_at=payload.eligible_close_at,
            notes=payload.notes,
        )
    return _profile_response(profile)


@router.delete("/{account_id}/profile", status_code=status.HTTP_204_NO_CONTENT)
def delete_iis_profile_endpoint(
    account_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    _require_account(session, account_id)
    delete_iis_profile(session, account_id=account_id)


# --- contribution endpoints ---


@router.get("/{account_id}/contributions", response_model=list[IisContributionResponse])
def list_iis_contributions_endpoint(
    account_id: int,
    tax_year: int | None = Query(default=None, ge=1900, le=9999),
    session: Session = Depends(session_for_request),
) -> list[IisContributionResponse]:
    _require_account(session, account_id)
    contributions = list_iis_contributions(session, account_id, tax_year=tax_year)
    return [_contribution_response(c) for c in contributions]


@router.post(
    "/{account_id}/contributions",
    response_model=IisContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_iis_contribution_endpoint(
    account_id: int,
    payload: IisContributionCreate,
    session: Session = Depends(session_for_request),
) -> IisContributionResponse:
    _require_account(session, account_id)
    if (
        get_iis_contribution_by_key(session, account_id=account_id, tax_year=payload.tax_year)
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"iis contribution for tax year {payload.tax_year} already exists",
        )
    contribution = create_iis_contribution(
        session,
        account_id=account_id,
        tax_year=payload.tax_year,
        amount=_amount_from_money(payload.amount),
        is_target_reached=payload.is_target_reached,
        notes=payload.notes,
    )
    return _contribution_response(contribution)


@router.patch(
    "/{account_id}/contributions/{contribution_id}",
    response_model=IisContributionResponse,
)
def update_iis_contribution_endpoint(
    account_id: int,
    contribution_id: int,
    payload: IisContributionUpdate,
    session: Session = Depends(session_for_request),
) -> IisContributionResponse:
    _require_account(session, account_id)
    contribution = update_iis_contribution(
        session,
        contribution_id,
        tax_year=payload.tax_year,
        amount=_amount_from_money(payload.amount) if payload.amount is not None else None,
        is_target_reached=payload.is_target_reached,
        notes=payload.notes,
    )
    return _contribution_response(contribution)


@router.delete(
    "/{account_id}/contributions/{contribution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_iis_contribution_endpoint(
    account_id: int,
    contribution_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    _require_account(session, account_id)
    delete_iis_contribution(session, contribution_id)


# --- tax benefit endpoints ---


@router.get("/{account_id}/benefits", response_model=list[TaxBenefitResponse])
def list_tax_benefits_endpoint(
    account_id: int,
    benefit_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(session_for_request),
) -> list[TaxBenefitResponse]:
    _require_account(session, account_id)
    if benefit_status is not None:
        _validate_tax_benefit_status(benefit_status)
    benefits = list_tax_benefits(session, account_id, status=benefit_status)
    return [_benefit_response(b) for b in benefits]


@router.post(
    "/{account_id}/benefits",
    response_model=TaxBenefitResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tax_benefit_endpoint(
    account_id: int,
    payload: TaxBenefitCreate,
    session: Session = Depends(session_for_request),
) -> TaxBenefitResponse:
    _require_account(session, account_id)
    _validate_tax_benefit_status(payload.status)
    if (
        get_tax_benefit_by_key(
            session,
            account_id=account_id,
            tax_year=payload.tax_year,
            benefit_type=payload.benefit_type,
        )
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"tax benefit for tax year {payload.tax_year} and type "
                f"{payload.benefit_type} already exists"
            ),
        )
    benefit = create_tax_benefit(
        session,
        account_id=account_id,
        tax_year=payload.tax_year,
        benefit_type=payload.benefit_type,
        status=payload.status,
        amount=_amount_from_money(payload.amount),
        received_at=payload.received_at,
        notes=payload.notes,
    )
    return _benefit_response(benefit)


@router.patch(
    "/{account_id}/benefits/{benefit_id}",
    response_model=TaxBenefitResponse,
)
def update_tax_benefit_endpoint(
    account_id: int,
    benefit_id: int,
    payload: TaxBenefitUpdate,
    session: Session = Depends(session_for_request),
) -> TaxBenefitResponse:
    _require_account(session, account_id)
    if payload.status is not None:
        _validate_tax_benefit_status(payload.status)
    benefit = update_tax_benefit(
        session,
        benefit_id,
        tax_year=payload.tax_year,
        benefit_type=payload.benefit_type,
        status=payload.status,
        amount=_amount_from_money(payload.amount) if payload.amount is not None else None,
        received_at=payload.received_at,
        notes=payload.notes,
    )
    return _benefit_response(benefit)


@router.delete(
    "/{account_id}/benefits/{benefit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_tax_benefit_endpoint(
    account_id: int,
    benefit_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    _require_account(session, account_id)
    delete_tax_benefit(session, benefit_id)
