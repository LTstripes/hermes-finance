"""Owner-managed in-kind boundary evidence (PERF-H2d)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain import InKindBoundaryCoverageState, InKindMovementKind
from hermes_finance.persistence import (
    InKindBoundaryCoverage as InKindBoundaryCoverageRecord,
)
from hermes_finance.persistence import (
    InKindMovement as InKindMovementRecord,
)
from hermes_finance.services.in_kind_boundary_coverage import (
    create_in_kind_boundary_coverage,
    create_in_kind_movement,
    get_in_kind_boundary_coverage,
    get_in_kind_movement,
    list_in_kind_boundary_coverages,
    list_in_kind_movements,
    update_in_kind_boundary_coverage,
)


class InKindBoundaryCoverageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    covered_from: date
    covered_to: date
    coverage_state: str = InKindBoundaryCoverageState.COMPLETE.value
    provenance_kind: str = Field(default="owner_attestation", min_length=1, max_length=64)
    provenance_reference: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class InKindBoundaryCoverageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int | None = None
    covered_from: date | None = None
    covered_to: date | None = None
    coverage_state: str | None = Field(default=None, min_length=1, max_length=16)
    provenance_kind: str | None = Field(default=None, min_length=1, max_length=64)
    provenance_reference: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class InKindBoundaryCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    account_id: int
    covered_from: date
    covered_to: date
    coverage_state: str
    provenance_kind: str
    provenance_reference: str | None
    notes: str | None


class InKindMovementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    event_date: date
    movement_kind: str = InKindMovementKind.EXTERNAL_IN.value
    source_account_id: int | None = None
    destination_account_id: int | None = None
    instrument_id: int | None = None
    quantity: Decimal | None = None
    provenance_kind: str = Field(default="owner_attestation", min_length=1, max_length=64)
    provenance_reference: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class InKindMovementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    reporting_month_id: int
    event_date: date
    source_account_id: int | None
    destination_account_id: int | None
    movement_kind: str
    instrument_id: int | None
    quantity: str | None
    provenance_kind: str
    provenance_reference: str | None
    notes: str | None


def _coverage_response(row: InKindBoundaryCoverageRecord) -> InKindBoundaryCoverageResponse:
    return InKindBoundaryCoverageResponse(
        id=row.id,
        account_id=row.account_id,
        covered_from=row.covered_from,
        covered_to=row.covered_to,
        coverage_state=row.coverage_state,
        provenance_kind=row.provenance_kind,
        provenance_reference=row.provenance_reference,
        notes=row.notes,
    )


def _movement_response(row: InKindMovementRecord) -> InKindMovementResponse:
    return InKindMovementResponse(
        id=row.id,
        reporting_month_id=row.reporting_month_id,
        event_date=row.event_date,
        source_account_id=row.source_account_id,
        destination_account_id=row.destination_account_id,
        movement_kind=row.movement_kind,
        instrument_id=row.instrument_id,
        quantity=None if row.quantity is None else str(row.quantity),
        provenance_kind=row.provenance_kind,
        provenance_reference=row.provenance_reference,
        notes=row.notes,
    )


coverage_router = APIRouter(
    prefix="/api/in-kind-boundary-coverages", tags=["in-kind-boundary-coverage"]
)


@coverage_router.get("", response_model=list[InKindBoundaryCoverageResponse])
def list_in_kind_boundary_coverages_endpoint(
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[InKindBoundaryCoverageResponse]:
    return [
        _coverage_response(row)
        for row in list_in_kind_boundary_coverages(session, account_id=account_id)
    ]


@coverage_router.post(
    "", response_model=InKindBoundaryCoverageResponse, status_code=status.HTTP_201_CREATED
)
def create_in_kind_boundary_coverage_endpoint(
    payload: InKindBoundaryCoverageCreate,
    session: Session = Depends(session_for_request),
) -> InKindBoundaryCoverageResponse:
    return _coverage_response(
        create_in_kind_boundary_coverage(session, **payload.model_dump())
    )


@coverage_router.get("/{coverage_id}", response_model=InKindBoundaryCoverageResponse)
def get_in_kind_boundary_coverage_endpoint(
    coverage_id: int,
    session: Session = Depends(session_for_request),
) -> InKindBoundaryCoverageResponse:
    return _coverage_response(get_in_kind_boundary_coverage(session, coverage_id))


@coverage_router.patch("/{coverage_id}", response_model=InKindBoundaryCoverageResponse)
def update_in_kind_boundary_coverage_endpoint(
    coverage_id: int,
    payload: InKindBoundaryCoverageUpdate,
    session: Session = Depends(session_for_request),
) -> InKindBoundaryCoverageResponse:
    return _coverage_response(
        update_in_kind_boundary_coverage(
            session, coverage_id, **payload.model_dump(exclude_unset=True)
        )
    )


movement_router = APIRouter(prefix="/api/in-kind-movements", tags=["in-kind-movement"])


@movement_router.get("", response_model=list[InKindMovementResponse])
def list_in_kind_movements_endpoint(
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[InKindMovementResponse]:
    return [_movement_response(row) for row in list_in_kind_movements(session, account_id=account_id)]


@movement_router.post("", response_model=InKindMovementResponse, status_code=status.HTTP_201_CREATED)
def create_in_kind_movement_endpoint(
    payload: InKindMovementCreate,
    session: Session = Depends(session_for_request),
) -> InKindMovementResponse:
    return _movement_response(create_in_kind_movement(session, **payload.model_dump()))


@movement_router.get("/{movement_id}", response_model=InKindMovementResponse)
def get_in_kind_movement_endpoint(
    movement_id: int,
    session: Session = Depends(session_for_request),
) -> InKindMovementResponse:
    return _movement_response(get_in_kind_movement(session, movement_id))
