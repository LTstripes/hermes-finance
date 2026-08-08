"""Accounts API (D04).

CRUD for the accounts reference dictionary. Money-free boundary: the API
layer maps Pydantic models to service calls and converts service exceptions
to HTTP codes via the unified error handlers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain import AccountStatus, AccountType
from hermes_finance.services.accounts import (
    create_account,
    delete_account,
    get_account,
    get_account_by_external_code,
    list_accounts,
    update_account,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    account_type: str = Field(min_length=1, max_length=16)
    external_code: str | None = Field(default=None, max_length=128)
    status: str = Field(default="active", min_length=1, max_length=16)
    include_in_capital: bool = True
    include_in_returns: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    account_type: str | None = Field(default=None, min_length=1, max_length=16)
    external_code: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, min_length=1, max_length=16)
    include_in_capital: bool | None = None
    include_in_returns: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    account_type: str
    status: str
    external_code: str | None
    include_in_capital: bool
    include_in_returns: bool
    notes: str | None


def _validate_account_type(value: str) -> str:
    try:
        AccountType(value)
    except ValueError as error:
        raise ValueError(f"unsupported account type: {value!r}") from error
    return value


def _validate_account_status(value: str) -> str:
    try:
        AccountStatus(value)
    except ValueError as error:
        raise ValueError(f"unsupported account status: {value!r}") from error
    return value


@router.get("", response_model=list[AccountResponse])
def list_accounts_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    session: Session = Depends(session_for_request),
) -> list[AccountResponse]:
    accounts = list_accounts(session)
    if status_filter is not None:
        _validate_account_status(status_filter)
        accounts = [a for a in accounts if a.status == status_filter]
    return [AccountResponse.model_validate(a) for a in accounts]


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account_endpoint(
    payload: AccountCreate,
    session: Session = Depends(session_for_request),
) -> AccountResponse:
    _validate_account_type(payload.account_type)
    _validate_account_status(payload.status)
    if payload.external_code is not None:
        existing = get_account_by_external_code(session, payload.external_code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"external_code '{payload.external_code}' already exists",
            )
    account = create_account(
        session,
        name=payload.name,
        account_type=payload.account_type,
        external_code=payload.external_code,
        status=payload.status,
        include_in_capital=payload.include_in_capital,
        include_in_returns=payload.include_in_returns,
        notes=payload.notes,
    )
    return AccountResponse.model_validate(account)


@router.get("/{account_id}", response_model=AccountResponse)
def get_account_endpoint(
    account_id: int,
    session: Session = Depends(session_for_request),
) -> AccountResponse:
    return AccountResponse.model_validate(get_account(session, account_id))


@router.patch("/{account_id}", response_model=AccountResponse)
def update_account_endpoint(
    account_id: int,
    payload: AccountUpdate,
    session: Session = Depends(session_for_request),
) -> AccountResponse:
    if payload.account_type is not None:
        _validate_account_type(payload.account_type)
    if payload.status is not None:
        _validate_account_status(payload.status)
    if payload.external_code is not None:
        existing = get_account_by_external_code(session, payload.external_code)
        if existing is not None and existing.id != account_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"external_code '{payload.external_code}' already exists",
            )
    account = update_account(
        session,
        account_id,
        name=payload.name,
        account_type=payload.account_type,
        external_code=payload.external_code,
        status=payload.status,
        include_in_capital=payload.include_in_capital,
        include_in_returns=payload.include_in_returns,
        notes=payload.notes,
    )
    return AccountResponse.model_validate(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account_endpoint(
    account_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_account(session, account_id)
