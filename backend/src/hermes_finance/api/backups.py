"""SQLite backup API (F04)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from hermes_finance.api.settings import _database_for_request
from hermes_finance.database import Database
from hermes_finance.services.backups import (
    BackupMetadata,
    BackupSourceMetadata,
    BackupStorageError,
    create_backup,
    list_backups,
)

router = APIRouter(prefix="/api/backups", tags=["backups"])


class BackupSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    size_bytes: int


class BackupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    size_bytes: int
    source_database: BackupSourceResponse


def _response(metadata: BackupMetadata) -> BackupResponse:
    return BackupResponse(
        id=metadata.id,
        name=metadata.name,
        created_at=metadata.created_at,
        size_bytes=metadata.size_bytes,
        source_database=BackupSourceResponse.model_validate(
            BackupSourceMetadata(
                name=metadata.source_database.name,
                size_bytes=metadata.source_database.size_bytes,
            )
        ),
    )


@router.post("", response_model=BackupResponse, status_code=status.HTTP_201_CREATED)
def create_backup_endpoint(
    database: Database = Depends(_database_for_request),
) -> BackupResponse:
    try:
        return _response(create_backup(database))
    except BackupStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backup storage is not available",
        ) from error


@router.get("", response_model=list[BackupResponse])
def list_backups_endpoint(
    database: Database = Depends(_database_for_request),
) -> list[BackupResponse]:
    try:
        return [_response(item) for item in list_backups(database)]
    except BackupStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backup storage is not available",
        ) from error
