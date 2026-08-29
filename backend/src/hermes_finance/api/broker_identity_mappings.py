"""Explicit broker identity mapping registry API (ADR 0016 Slice A)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.persistence import BrokerIdentityMapping
from hermes_finance.services.broker_identity_mappings import (
    BrokerIdentityMappingConflictError,
    BrokerIdentitySubjectKind,
    confirm_mapping,
    get_mapping,
    list_mappings,
    remap_mapping,
    revoke_mapping,
)

router = APIRouter(prefix="/api/broker-identity-mappings", tags=["broker-identity-mappings"])


class BrokerIdentityMappingConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32)
    subject_kind: BrokerIdentitySubjectKind
    provider_identity: str = Field(min_length=1, max_length=128)
    hermes_target_id: int = Field(gt=0)
    observed_isin: str | None = Field(default=None, max_length=12)
    source_as_of: datetime | None = None
    captured_at: datetime | None = None


class BrokerIdentityMappingRevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=256)


class BrokerIdentityMappingRemapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hermes_target_id: int = Field(gt=0)
    observed_isin: str | None = Field(default=None, max_length=12)
    source_as_of: datetime | None = None
    captured_at: datetime | None = None


class BrokerIdentityMappingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_id: int
    provider: str
    subject_kind: str
    provider_identity: str
    hermes_target_id: int
    status: str
    observed_isin: str | None
    confirmed_at: datetime
    source_as_of: datetime | None
    captured_at: datetime | None
    predecessor_mapping_id: int | None
    successor_mapping_id: int | None
    revoked_at: datetime | None
    revoke_reason: str | None


def _out(row: BrokerIdentityMapping) -> BrokerIdentityMappingOut:
    return BrokerIdentityMappingOut(
        mapping_id=row.id,
        provider=row.provider,
        subject_kind=row.subject_kind,
        provider_identity=row.provider_identity,
        hermes_target_id=row.hermes_target_id,
        status=row.status,
        observed_isin=row.observed_isin,
        confirmed_at=row.confirmed_at,
        source_as_of=row.source_as_of,
        captured_at=row.captured_at,
        predecessor_mapping_id=row.predecessor_mapping_id,
        successor_mapping_id=row.successor_mapping_id,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
    )


def _raise_service_error(error: Exception) -> None:
    if isinstance(error, BrokerIdentityMappingConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.get("", response_model=list[BrokerIdentityMappingOut])
def list_broker_identity_mappings_endpoint(
    provider: str | None = Query(default=None, min_length=1, max_length=32),
    session: Session = Depends(session_for_request),
) -> list[BrokerIdentityMappingOut]:
    try:
        rows = list_mappings(session, provider=provider)
    except ValueError as error:
        _raise_service_error(error)
        raise
    return [_out(row) for row in rows]


@router.post("", response_model=BrokerIdentityMappingOut)
def confirm_broker_identity_mapping_endpoint(
    payload: BrokerIdentityMappingConfirmIn,
    session: Session = Depends(session_for_request),
) -> BrokerIdentityMappingOut:
    try:
        row = confirm_mapping(
            session,
            provider=payload.provider,
            subject_kind=payload.subject_kind,
            provider_identity=payload.provider_identity,
            hermes_target_id=payload.hermes_target_id,
            observed_isin=payload.observed_isin,
            source_as_of=payload.source_as_of,
            captured_at=payload.captured_at,
        )
    except (BrokerIdentityMappingConflictError, ValueError) as error:
        _raise_service_error(error)
        raise
    return _out(row)


@router.post("/{mapping_id}/revoke", response_model=BrokerIdentityMappingOut)
def revoke_broker_identity_mapping_endpoint(
    mapping_id: int,
    payload: BrokerIdentityMappingRevokeIn,
    session: Session = Depends(session_for_request),
) -> BrokerIdentityMappingOut:
    try:
        row = revoke_mapping(session, mapping_id, reason=payload.reason)
    except (BrokerIdentityMappingConflictError, ValueError) as error:
        _raise_service_error(error)
        raise
    return _out(row)


@router.post("/{mapping_id}/remap", response_model=BrokerIdentityMappingOut)
def remap_broker_identity_mapping_endpoint(
    mapping_id: int,
    payload: BrokerIdentityMappingRemapIn,
    session: Session = Depends(session_for_request),
) -> BrokerIdentityMappingOut:
    try:
        row = remap_mapping(
            session,
            mapping_id,
            hermes_target_id=payload.hermes_target_id,
            observed_isin=payload.observed_isin,
            source_as_of=payload.source_as_of,
            captured_at=payload.captured_at,
        )
    except (BrokerIdentityMappingConflictError, ValueError) as error:
        _raise_service_error(error)
        raise
    return _out(row)


@router.get("/{mapping_id}", response_model=BrokerIdentityMappingOut)
def get_broker_identity_mapping_endpoint(
    mapping_id: int,
    session: Session = Depends(session_for_request),
) -> BrokerIdentityMappingOut:
    return _out(get_mapping(session, mapping_id))
