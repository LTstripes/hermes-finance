"""Explicit membership form with single-use, restore-sensitive transient tokens."""

from datetime import date
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import text
from sqlalchemy.orm import Session

from hermes_finance.api.performance_readiness import (
    PerformanceReadinessResponse,
    read_performance_readiness,
)
from hermes_finance.api.settings import _database_for_request, session_for_request
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import PerformanceScope
from hermes_finance.persistence import Account
from hermes_finance.services.historical_membership import (
    Interval,
    history,
    stage_replace,
    state_identity,
)

router = APIRouter(prefix="/api/performance/membership", tags=["performance"])


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int = Field(gt=0)
    start_date: date
    end_date: date
    scope: Literal["account", "portfolio"]


class FiniteInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_from: date
    effective_to: date
    include_in_returns: StrictBool


class Correction(Context):
    form_token: str = Field(min_length=1, max_length=128)
    replaced_ids: list[int]
    replacements: list[FiniteInterval]
    attested: Literal[True]


class Registry:
    """Bounded process-local forms, not an audit log or financial generation.

    Restart loses all forms (fail closed). Restore admission changes the epoch.
    A token is consumed even on a rejected write; the user must reread/re-attest.
    """

    def __init__(self):
        self.lock = Lock()
        self.tokens: dict[str, tuple[float, int, str, str]] = {}

    def issue(self, epoch: int, context: Context, identity: str) -> str:
        with self.lock:
            now = monotonic()
            self.tokens = {k: v for k, v in self.tokens.items() if v[0] > now and v[1] == epoch}
            if len(self.tokens) >= 1024:
                self.tokens.pop(next(iter(self.tokens)))
            token = token_urlsafe(32)
            self.tokens[token] = (now + 1800, epoch, context.model_dump_json(), identity)
            return token

    def consume(self, token: str, epoch: int, context: Context) -> str:
        with self.lock:
            entry = self.tokens.pop(token, None)
        if (
            entry is None
            or entry[0] <= monotonic()
            or entry[1] != epoch
            or entry[2] != context.model_dump_json()
        ):
            raise ValueError("Form expired, restored or already submitted; reread before saving")
        # A later A -> B -> A edit must not revive another already-open form.
        with self.lock:
            self.tokens.clear()
        return entry[3]


_registry_lock = Lock()


def _registry(request: Request) -> Registry:
    with _registry_lock:
        if not hasattr(request.app.state, "membership_forms"):
            request.app.state.membership_forms = Registry()
        return request.app.state.membership_forms


def _context(value: Context) -> Context:
    if value.start_date >= value.end_date:
        raise HTTPException(422, "start_date must precede end_date")
    return Context(**{key: getattr(value, key) for key in Context.model_fields})


def _read(
    request: Request, session: Session, context: Context, expected_identity: str | None = None
) -> dict[str, object]:
    with coherent_read_snapshot(session):
        if session.get(Account, context.account_id) is None:
            raise HTTPException(404, "Account not found")
        identity = state_identity(session)
        if expected_identity is not None and identity != expected_identity:
            raise HTTPException(409, "Write read-back changed; inspect current history")
        rows = [
            dict(
                id=r.id,
                effective_from=r.effective_from,
                effective_to=r.effective_to,
                include_in_returns=r.include_in_returns,
            )
            for r in history(session, context.account_id)
        ]
        readiness = read_performance_readiness(
            request,
            start_date=context.start_date,
            end_date=context.end_date,
            scope=PerformanceScope(context.scope),
            account_id=context.account_id if context.scope == "account" else None,
            session=session,
        )
        if not isinstance(readiness, PerformanceReadinessResponse):
            raise HTTPException(503, "Membership/readiness read-back did not complete")
        return {
            **context.model_dump(),
            "rows": rows,
            "identity": identity,
            "form_token": _registry(request).issue(
                _database_for_request(request).maintenance.form_epoch, context, identity
            ),
            "readiness": readiness,
        }


@router.get("")
def read_membership(
    request: Request, context: Context = Depends(), session: Session = Depends(session_for_request)
):
    for key in Context.model_fields:
        if len(request.query_params.getlist(key)) > 1:
            raise HTTPException(422, "Membership context must not be repeated")
    return _read(request, session, _context(context))


@router.post("")
def correct_membership(
    payload: Correction, request: Request, session: Session = Depends(session_for_request)
):
    context = _context(payload)
    try:
        session.execute(text("UPDATE reporting_months SET status = status WHERE 0"))
        session.expire_all()
        identity = _registry(request).consume(
            payload.form_token, _database_for_request(request).maintenance.form_epoch, context
        )
        affected = stage_replace(
            session,
            account_id=context.account_id,
            expected_identity=identity,
            replaced_ids=payload.replaced_ids,
            replacements=[Interval(**r.model_dump()) for r in payload.replacements],
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    except Exception:
        session.rollback()
        raise
    # A commit acknowledgement alone is never displayed as a successful correction.
    return {**_read(request, session, context, str(affected["identity"])), "affected": affected}
