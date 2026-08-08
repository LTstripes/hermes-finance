"""Reporting months API (D01 + D02).

CRUD and status management for reporting months.
Domain logic lives in ``services.reporting_months``; this module only
provides the HTTP boundary and maps service exceptions to HTTP codes via
the unified error handlers registered in ``api.errors``.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.month_clone import clone_reporting_month
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    delete_reporting_month,
    get_reporting_month,
    get_reporting_month_by_period,
    list_reporting_months,
    reopen_reporting_month,
    update_reporting_month,
)

router = APIRouter(prefix="/api/months", tags=["months"])


class ReportingMonthCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)
    snapshot_date: date
    source: str | None = Field(default=None, min_length=1, max_length=32)


class ReportingMonthUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_date: date | None = None
    source: str | None = Field(default=None, min_length=1, max_length=32)


class ReportingMonthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    month: int
    status: str
    snapshot_date: date
    source: str


@router.get("", response_model=list[ReportingMonthResponse])
def list_months(
    session: Session = Depends(session_for_request),
) -> list[ReportingMonthResponse]:
    months = list_reporting_months(session)
    return [ReportingMonthResponse.model_validate(m) for m in months]


@router.post("", response_model=ReportingMonthResponse, status_code=status.HTTP_201_CREATED)
def create_month(
    payload: ReportingMonthCreate,
    session: Session = Depends(session_for_request),
) -> ReportingMonthResponse:
    if get_reporting_month_by_period(session, year=payload.year, month=payload.month) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"reporting month {payload.year:04d}-{payload.month:02d} already exists",
        )
    month = create_reporting_month(
        session,
        year=payload.year,
        month=payload.month,
        snapshot_date=payload.snapshot_date,
        source=payload.source if payload.source is not None else "manual",
    )
    return ReportingMonthResponse.model_validate(month)


@router.get("/{month_id}", response_model=ReportingMonthResponse)
def get_month(
    month_id: int,
    session: Session = Depends(session_for_request),
) -> ReportingMonthResponse:
    return ReportingMonthResponse.model_validate(get_reporting_month(session, month_id))


@router.patch("/{month_id}", response_model=ReportingMonthResponse)
def update_month(
    month_id: int,
    payload: ReportingMonthUpdate,
    session: Session = Depends(session_for_request),
) -> ReportingMonthResponse:
    month = update_reporting_month(
        session,
        month_id,
        snapshot_date=payload.snapshot_date,
        source=payload.source,
    )
    return ReportingMonthResponse.model_validate(month)


@router.delete("/{month_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_month(
    month_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_reporting_month(session, month_id)


class ReportingMonthClone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)
    snapshot_date: date


@router.post(
    "/{month_id}/clone", response_model=ReportingMonthResponse, status_code=status.HTTP_201_CREATED
)
def clone_month(
    month_id: int,
    payload: ReportingMonthClone,
    session: Session = Depends(session_for_request),
) -> ReportingMonthResponse:
    if get_reporting_month_by_period(session, year=payload.year, month=payload.month) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"reporting month {payload.year:04d}-{payload.month:02d} already exists",
        )
    cloned = clone_reporting_month(
        session,
        month_id,
        target_year=payload.year,
        target_month=payload.month,
        snapshot_date=payload.snapshot_date,
    )
    return ReportingMonthResponse.model_validate(cloned)


@router.post("/{month_id}/close", response_model=ReportingMonthResponse)
def close_month(
    month_id: int,
    session: Session = Depends(session_for_request),
) -> ReportingMonthResponse:
    month = get_reporting_month(session, month_id)
    if month.snapshot_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="snapshot_date is required before closing a reporting month",
        )
    closed = close_reporting_month(session, month_id)
    return ReportingMonthResponse.model_validate(closed)


@router.post("/{month_id}/reopen", response_model=ReportingMonthResponse)
def reopen_month(
    month_id: int,
    session: Session = Depends(session_for_request),
) -> ReportingMonthResponse:
    reopened = reopen_reporting_month(session, month_id)
    return ReportingMonthResponse.model_validate(reopened)
