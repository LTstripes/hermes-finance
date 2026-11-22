"""Deposits API (D05).

CRUD for deposit snapshots with optimistic concurrency via If-Match.
Server-side recalculation of expected_monthly_interest stays in the
service layer (B10); this module only maps the HTTP boundary.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import DepositType, PercentageRate, RubleAmount
from hermes_finance.services import alfa_savings
from hermes_finance.services.deposits import (
    create_deposit_snapshot,
    delete_deposit_snapshot,
    list_deposit_snapshots,
    update_deposit_snapshot,
)

router = APIRouter(prefix="/api/deposits", tags=["deposits"])


class DepositCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    account_id: int
    name: str = Field(min_length=1, max_length=128)
    deposit_type: str = Field(min_length=1, max_length=16)
    balance: MoneyValue
    annual_rate: str = Field(min_length=1)
    actual_interest_received: MoneyValue | None = None
    notes: str | None = Field(default=None, max_length=2000)


class DepositUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    deposit_type: str | None = Field(default=None, min_length=1, max_length=16)
    balance: MoneyValue | None = None
    annual_rate: str | None = Field(default=None, min_length=1)
    actual_interest_received: MoneyValue | None = None
    notes: str | None = Field(default=None, max_length=2000)


class DepositResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    account_id: int
    name: str
    deposit_type: str
    balance: MoneyValue
    annual_rate: str
    expected_monthly_interest: MoneyValue
    actual_interest_received: MoneyValue
    notes: str | None
    updated_at: datetime


def _validate_deposit_type(value: str) -> str:
    try:
        DepositType(value)
    except ValueError as error:
        raise ValueError("unsupported deposit type") from error
    return value


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _response_from_snapshot(snapshot: object) -> DepositResponse:
    return DepositResponse(
        id=snapshot.id,
        reporting_month_id=snapshot.reporting_month_id,
        account_id=snapshot.account_id,
        name=snapshot.name,
        deposit_type=snapshot.deposit_type,
        balance=MoneyValue(
            amount=RubleAmount(snapshot.balance_kopecks).to_api(),
            currency="RUB",
        ),
        annual_rate=PercentageRate(snapshot.annual_rate_basis_points).to_api(),
        expected_monthly_interest=MoneyValue(
            amount=RubleAmount(snapshot.expected_monthly_interest_kopecks).to_api(),
            currency="RUB",
        ),
        actual_interest_received=MoneyValue(
            amount=RubleAmount(snapshot.actual_interest_received_kopecks).to_api(),
            currency="RUB",
        ),
        notes=snapshot.notes,
        updated_at=snapshot.updated_at,
    )


def _parse_if_match(if_match: str | None) -> datetime | None:
    if if_match is None:
        return None
    return datetime.fromisoformat(if_match)


class AlfaSavingsPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    month_id: int = Field(gt=0)
    csv: str = Field(min_length=1, max_length=8 * 1024 * 1024)
    full_month: bool = False
    bindings: dict[str, int] = Field(default_factory=dict)

    @field_validator("bindings", mode="before")
    @classmethod
    def validate_bindings(cls, value):
        # Keep caller-supplied private identifiers out of nested error field names.
        if not isinstance(value, dict) or any(
            not re.fullmatch(r"[0-9a-f]{64}", key) or type(account_id) is not int or account_id <= 0
            for key, account_id in value.items()
        ):
            raise ValueError("Неверная привязка счёта.")
        return value


class AlfaSavingsApply(AlfaSavingsPreview):
    source_key: str = Field(pattern="^[0-9a-f]{64}$")
    token: str = Field(pattern="^[0-9a-f]{64}$")


@router.post("/alfa/preview")
def preview_alfa_savings(
    payload: AlfaSavingsPreview, response: Response, session: Session = Depends(session_for_request)
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return alfa_savings.preview(session, **payload.model_dump())


@router.post("/alfa/apply", response_model=DepositResponse)
def apply_alfa_savings(
    payload: AlfaSavingsApply, response: Response, session: Session = Depends(session_for_request)
) -> DepositResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        snapshot = alfa_savings.apply(session, **payload.model_dump())
    except alfa_savings.StaleSavingsPreview as error:
        raise HTTPException(409, str(error)) from error
    return _response_from_snapshot(snapshot)


@router.get("", response_model=list[DepositResponse])
def list_deposits_endpoint(
    month_id: int = Query(...),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[DepositResponse]:
    snapshots = list_deposit_snapshots(session)
    snapshots = [s for s in snapshots if s.reporting_month_id == month_id]
    if account_id is not None:
        snapshots = [s for s in snapshots if s.account_id == account_id]
    return [_response_from_snapshot(s) for s in snapshots]


@router.post(
    "",
    response_model=DepositResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_deposit_endpoint(
    payload: DepositCreate,
    session: Session = Depends(session_for_request),
) -> DepositResponse:
    _validate_deposit_type(payload.deposit_type)
    snapshot = create_deposit_snapshot(
        session,
        reporting_month_id=payload.reporting_month_id,
        account_id=payload.account_id,
        name=payload.name,
        deposit_type=payload.deposit_type,
        balance=_amount(payload.balance),
        annual_rate=PercentageRate.from_api(payload.annual_rate),
        actual_interest_received=_amount(payload.actual_interest_received)
        if payload.actual_interest_received is not None
        else "0.00",
        notes=payload.notes,
    )
    return _response_from_snapshot(snapshot)


@router.patch("/{snapshot_id}", response_model=DepositResponse)
def update_deposit_endpoint(
    snapshot_id: int,
    payload: DepositUpdate,
    if_match: str | None = Header(default=None),
    session: Session = Depends(session_for_request),
) -> DepositResponse:
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="If-Match header is required for deposit updates",
        )
    expected_updated_at = _parse_if_match(if_match)
    if payload.deposit_type is not None:
        _validate_deposit_type(payload.deposit_type)
    snapshot = update_deposit_snapshot(
        session,
        snapshot_id,
        name=payload.name,
        deposit_type=payload.deposit_type,
        balance=_amount(payload.balance) if payload.balance is not None else None,
        annual_rate=PercentageRate.from_api(payload.annual_rate)
        if payload.annual_rate is not None
        else None,
        actual_interest_received=_amount(payload.actual_interest_received)
        if payload.actual_interest_received is not None
        else None,
        notes=payload.notes,
        expected_updated_at=expected_updated_at,
    )
    return _response_from_snapshot(snapshot)


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deposit_endpoint(
    snapshot_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_deposit_snapshot(session, snapshot_id)
