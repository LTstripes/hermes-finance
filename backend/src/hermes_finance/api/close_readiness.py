"""Read-only close-readiness API (R07-04 / issue #136)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import _database_for_request, session_for_request
from hermes_finance.database import Database
from hermes_finance.services.backups import BackupStorageError, list_backups
from hermes_finance.services.close_readiness import (
    CloseReadiness,
    CloseReadinessBackup,
    CloseReadinessItem,
    build_close_readiness,
)

router = APIRouter(prefix="/api/months", tags=["close-readiness"])


class CloseReadinessItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str
    code: str
    message: str
    context: dict[str, object] = Field(default_factory=dict)


class CloseReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    status: str
    snapshot_date: date | None
    source: str
    can_close: bool
    items: list[CloseReadinessItemOut]


def _item_out(item: CloseReadinessItem) -> CloseReadinessItemOut:
    return CloseReadinessItemOut(
        severity=item.severity.value,
        code=item.code,
        message=item.message,
        context=item.context,
    )


def _readiness_out(result: CloseReadiness) -> CloseReadinessOut:
    return CloseReadinessOut(
        year=result.year,
        month=result.month,
        status=result.status,
        snapshot_date=result.snapshot_date,
        source=result.source,
        can_close=result.can_close,
        items=[_item_out(item) for item in result.items],
    )


def _latest_backup(database: Database) -> CloseReadinessBackup | None:
    try:
        backups = list_backups(database)
    except BackupStorageError:
        return None
    if not backups:
        return None
    latest = backups[0]
    return CloseReadinessBackup(created_at=latest.created_at, name=latest.name)


@router.get("/{month_id}/close-readiness", response_model=CloseReadinessOut)
def get_close_readiness(
    month_id: int,
    request: Request,
    session: Session = Depends(session_for_request),
    database: Database = Depends(_database_for_request),
) -> CloseReadinessOut:
    today = moscow_today(request)
    result = build_close_readiness(
        session,
        month_id,
        today=today,
        latest_backup=_latest_backup(database),
    )
    return _readiness_out(result)
