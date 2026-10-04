"""Bounded Owner C2 actions and exact C3 endpoint eligibility, without returns."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import ClassNoCrossingCoverage
from hermes_finance.services.class_endpoint_eligibility import (
    class_endpoint_eligibility,
    coverage_response,
    save_no_crossing_coverage,
)


class CoverageWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_class: Literal["stock", "bond", "gold"]
    covered_from: date
    covered_to: date
    coverage_state: Literal["complete", "unknown", "revoked"]
    provenance_kind: Literal["owner_attestation"]
    provenance_reference: str | None = Field(default=None, min_length=1, max_length=128)
    opening_inventory_complete: StrictBool = False
    closing_inventory_complete: StrictBool = False


class CoverageResponse(CoverageWrite):
    id: int
    revision: int


class EndpointResponse(BaseModel):
    requested_class: str
    requested_opening_date: date
    requested_closing_date: date
    historical_account_ids: list[int]
    actual_opening_date: date | None
    actual_closing_date: date | None
    currency: str
    opening_value_kopecks: int | None
    closing_value_kopecks: int | None
    coverage_state: str
    coverage_provenance: list[CoverageResponse]
    status: Literal["eligible", "unavailable", "unsupported"]
    reason_codes: list[str]


router = APIRouter(prefix="/api/class-evidence", tags=["class-evidence"])


@router.get("/endpoints", response_model=EndpointResponse)
def endpoints(
    asset_class: str,
    start_date: date,
    end_date: date,
    session: Session = Depends(session_for_request),
) -> dict:
    return class_endpoint_eligibility(
        session, asset_class=asset_class, start_date=start_date, end_date=end_date
    )


@router.get("/coverages", response_model=list[CoverageResponse])
def coverages(session: Session = Depends(session_for_request)) -> list[dict]:
    with coherent_read_snapshot(session):
        return [
            coverage_response(row)
            for row in session.scalars(
                select(ClassNoCrossingCoverage).order_by(ClassNoCrossingCoverage.id)
            )
        ]


@router.post("/coverages", response_model=CoverageResponse, status_code=201)
def create(payload: CoverageWrite, session: Session = Depends(session_for_request)) -> dict:
    return coverage_response(save_no_crossing_coverage(session, **payload.model_dump()))


@router.put("/coverages/{coverage_id}", response_model=CoverageResponse)
def correct(
    coverage_id: int,
    payload: CoverageWrite,
    if_match: str | None = Header(default=None),
    session: Session = Depends(session_for_request),
) -> dict:
    if if_match is None:
        raise HTTPException(428, "If-Match revision is required")
    if not if_match.isascii() or not if_match.isdecimal() or len(if_match) > 10:
        raise HTTPException(400, "If-Match must be an ASCII integer revision")
    return coverage_response(
        save_no_crossing_coverage(
            session,
            coverage_id=coverage_id,
            expected_revision=int(if_match),
            **payload.model_dump(),
        )
    )
