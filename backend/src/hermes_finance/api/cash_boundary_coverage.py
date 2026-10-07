"""Owner-managed cash-boundary completeness evidence (PERF-H2b)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.performance_evidence_guard import preparation_session
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import CashBoundaryCoverageState
from hermes_finance.domain.source_cash_coverage import SourceCashApplyRequest, SourceCashIntent
from hermes_finance.persistence import CashBoundaryCoverage as CashBoundaryCoverageRecord
from hermes_finance.services.cash_boundary_coverage import (
    create_cash_boundary_coverage,
    effective_cash_boundary_row,
    get_cash_boundary_coverage,
    list_cash_boundary_coverages,
    update_cash_boundary_coverage,
)
from hermes_finance.services.source_cash_coverage import (
    apply_source_cash_coverage,
    latest,
    preview_source_cash_coverage,
    read_source_cash_coverage,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/cash-boundary-coverages", tags=["cash-boundary-coverage"])


class CashBoundaryCoverageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    covered_from: date
    covered_to: date
    coverage_state: str = CashBoundaryCoverageState.COMPLETE.value
    provenance_kind: str = Field(default="owner_attestation", min_length=1, max_length=64)
    provenance_reference: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class CashBoundaryCoverageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int | None = None
    covered_from: date | None = None
    covered_to: date | None = None
    coverage_state: str | None = Field(default=None, min_length=1, max_length=16)
    provenance_kind: str | None = Field(default=None, min_length=1, max_length=64)
    provenance_reference: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class CashBoundaryCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    account_id: int
    covered_from: date
    covered_to: date
    coverage_state: str
    provenance_kind: str
    provenance_reference: str | None
    notes: str | None
    source_acceptance: dict | None = None


def _response(row: CashBoundaryCoverageRecord, session=None) -> CashBoundaryCoverageResponse:
    acceptance = None
    if session is not None:
        from hermes_finance.domain.historical_owner_flows import SOURCE_CASH_PROVENANCE

        if row.provenance_kind == SOURCE_CASH_PROVENANCE or latest(session, row.id):
            acceptance = read_source_cash_coverage(session, row.id)
            row = effective_cash_boundary_row(session, row)
    return CashBoundaryCoverageResponse(
        id=row.id,
        account_id=row.account_id,
        covered_from=row.covered_from,
        covered_to=row.covered_to,
        coverage_state=row.coverage_state,
        provenance_kind=row.provenance_kind,
        provenance_reference=row.provenance_reference,
        notes=row.notes,
        source_acceptance=acceptance,
    )


@router.get("", response_model=list[CashBoundaryCoverageResponse])
def list_cash_boundary_coverages_endpoint(
    account_id: int | None = Query(default=None),
    session: Session = Depends(preparation_session),
) -> list[CashBoundaryCoverageResponse]:
    with coherent_read_snapshot(session):
        return [
            _response(row, session)
            for row in list_cash_boundary_coverages(session, account_id=account_id)
        ]


@router.post("", response_model=CashBoundaryCoverageResponse, status_code=status.HTTP_201_CREATED)
def create_cash_boundary_coverage_endpoint(
    payload: CashBoundaryCoverageCreate,
    session: Session = Depends(preparation_session),
) -> CashBoundaryCoverageResponse:
    return _response(
        create_cash_boundary_coverage(
            session,
            account_id=payload.account_id,
            covered_from=payload.covered_from,
            covered_to=payload.covered_to,
            coverage_state=payload.coverage_state,
            provenance_kind=payload.provenance_kind,
            provenance_reference=payload.provenance_reference,
            notes=payload.notes,
        )
    )


@router.post("/preview")
def preview_source_endpoint(
    request: SourceCashIntent, session: Session = Depends(preparation_session)
):
    try:
        return preview_source_cash_coverage(session, request)
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/apply")
def apply_source_endpoint(
    request: SourceCashApplyRequest, session: Session = Depends(preparation_session)
):
    intent = SourceCashIntent.model_validate(
        request.model_dump(exclude={"request_id", "confirmation_digest"})
    )
    try:
        return apply_source_cash_coverage(
            session,
            intent,
            confirmation_digest=request.confirmation_digest,
            request_id=request.request_id,
        )
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/{coverage_id}", response_model=CashBoundaryCoverageResponse)
def get_cash_boundary_coverage_endpoint(
    coverage_id: int,
    session: Session = Depends(preparation_session),
) -> CashBoundaryCoverageResponse:
    with coherent_read_snapshot(session):
        return _response(get_cash_boundary_coverage(session, coverage_id), session)


@router.patch("/{coverage_id}", response_model=CashBoundaryCoverageResponse)
def update_cash_boundary_coverage_endpoint(
    coverage_id: int,
    payload: CashBoundaryCoverageUpdate,
    session: Session = Depends(preparation_session),
) -> CashBoundaryCoverageResponse:
    return _response(
        update_cash_boundary_coverage(
            session,
            coverage_id,
            **payload.model_dump(exclude_unset=True),
        )
    )
