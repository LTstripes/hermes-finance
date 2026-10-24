"""Command-scoped intentional empty Close and immutable lost-ACK receipts (#952)."""

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.persistence import IntentionalEmptyCloseReceipt, ReportingMonth
from hermes_finance.services.reporting_months import (
    CLOSE_EMPTY_MANUAL_MONTH_CODE,
    CloseGuardError,
    close_hard_guards,
    get_reporting_month,
    reserve_close_writer,
)

POLICY_VERSION = "intentional_empty_manual_month_v1"


class EmptyCloseIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    month_id: int = Field(strict=True, gt=0)
    year: int = Field(strict=True, ge=1, le=9999)
    month: int = Field(strict=True, ge=1, le=12)
    snapshot_date: date
    expected_identity: str = Field(pattern=r"^[a-f0-9]{64}$")


class IntentionalEmptyCloseCommand(EmptyCloseIdentity):
    command: Literal["close_intentionally_empty_manual_month"]
    policy_version: Literal["intentional_empty_manual_month_v1"]
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def empty_close_identity(session: Session, month: ReportingMonth) -> EmptyCloseIdentity:
    """Exact persisted header incarnation/revision, with close-history ABA protection.

    No GET-time consent or data is saved. Child/source facts and every hard guard
    are re-read on execution; this token identifies the period/header lifecycle,
    not a claim of economic completeness or source acceptance.
    """
    last_request = session.scalar(
        select(IntentionalEmptyCloseReceipt.request_id)
        .where(IntentionalEmptyCloseReceipt.month_id == month.id)
        .order_by(IntentionalEmptyCloseReceipt.id.desc())
        .limit(1)
    )
    material = [
        month.id,
        month.year,
        month.month,
        month.period_start.isoformat(),
        month.period_end.isoformat(),
        month.snapshot_date.isoformat(),
        month.source,
        month.status,
        month.created_at.isoformat(),
        month.updated_at.isoformat(),
        last_request,
        # Existing request epoch retires confirmations on process/database
        # replacement and restore; committed original-intent ACK remains durable.
        session.info.get("source_intake_epoch", "direct-service"),
    ]
    return EmptyCloseIdentity(
        month_id=month.id,
        year=month.year,
        month=month.month,
        snapshot_date=month.snapshot_date,
        expected_identity=_digest(material),
    )


@coherent_read_operation
def read_intentional_empty_close(session: Session, month_id: int, request_id: str):
    receipt = session.scalar(
        select(IntentionalEmptyCloseReceipt).where(
            IntentionalEmptyCloseReceipt.month_id == month_id,
            IntentionalEmptyCloseReceipt.request_id == request_id,
        )
    )
    if receipt is None:
        raise LookupError("intentional empty Close receipt was not found")
    return receipt


def close_intentionally_empty_month(
    session: Session, month_id: int, command: IntentionalEmptyCloseCommand
) -> IntentionalEmptyCloseReceipt:
    # Revalidate even direct Python callers; no untyped service bypass.
    command = IntentionalEmptyCloseCommand.model_validate(command.model_dump())
    fingerprint = _digest(command.model_dump(mode="json"))
    try:
        reserve_close_writer(session, month_id)
        prior = session.scalar(
            select(IntentionalEmptyCloseReceipt).where(
                IntentionalEmptyCloseReceipt.request_id == command.request_id
            )
        )
        if prior is not None:
            if prior.month_id != month_id or prior.intent_digest != fingerprint:
                raise CloseGuardError(
                    "empty_close_request_conflict", "Close intent differs from receipt", 409
                )
            # Historical ACK only, including after Reopen/deletion; never reclose.
            session.rollback()
            return prior

        month = get_reporting_month(session, month_id)
        session.refresh(month)
        if month.status != "draft" or month.source != "manual":
            raise CloseGuardError("empty_close_not_manual_draft", "A MANUAL DRAFT is required", 409)
        blockers = close_hard_guards(month, session)
        other = [pair for pair in blockers if pair[0] != CLOSE_EMPTY_MANUAL_MONTH_CODE]
        if other:
            raise CloseGuardError(*other[0])
        current = empty_close_identity(session, month)
        supplied = EmptyCloseIdentity.model_validate(
            command.model_dump(include=set(EmptyCloseIdentity.model_fields))
        )
        if supplied != current or command.month_id != month_id:
            raise CloseGuardError(
                "empty_close_identity_changed", "Close period identity changed", 409
            )
        if not any(code == CLOSE_EMPTY_MANUAL_MONTH_CODE for code, _ in blockers):
            raise CloseGuardError(
                "empty_close_facts_present", "The month contains saved actual facts", 409
            )
        receipt = IntentionalEmptyCloseReceipt(
            request_id=command.request_id,
            intent_digest=fingerprint,
            month_id=month.id,
            year=month.year,
            month=month.month,
            snapshot_date=month.snapshot_date,
            expected_identity=current.expected_identity,
            reason=command.reason,
            policy_version=POLICY_VERSION,
            closed_at=datetime.now(UTC),
        )
        session.add(receipt)
        month.status = "closed"
        session.commit()
        session.refresh(receipt)
        return receipt
    except BaseException:
        session.rollback()
        raise
