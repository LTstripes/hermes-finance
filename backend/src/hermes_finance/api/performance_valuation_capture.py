"""Version-bound observed PRE/POST valuation capture adapter (#533).

Reads the canonical availability projection, exposes only the exact explicit
targets that need fresh evidence together with the current material signature,
and publishes one actually observed side per submission.  It contains no
derivation from flows, snapshots or interpolation and no provider access.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, DecimalException
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy.orm import Session

from hermes_finance.api.errors import ErrorResponse
from hermes_finance.api.performance_availability import ExactMoneyOut
from hermes_finance.api.performance_readiness import (
    PerformanceReadinessResponse,
    read_performance_readiness,
)
from hermes_finance.api.settings import _database_for_request, session_for_request
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import PerformanceScope
from hermes_finance.persistence import Account
from hermes_finance.services.performance_availability import _validate_request
from hermes_finance.services.valuation_capture import (
    CaptureSide,
    CaptureTarget,
    ValuationCaptureProjection,
    stage_observed_valuation_capture,
    valuation_capture_projection_for_interval,
)

router = APIRouter(prefix="/api/performance/valuation-captures", tags=["performance"])


class CaptureSideOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    relation: str
    observed_date: date
    total_value: ExactMoneyOut
    performance_currency: str
    coverage: str
    quality: str
    provenance_kind: str
    bound: bool
    # Free-form provenance references are intentionally never echoed here.


class CaptureTargetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundary_group_id: int | None
    flow_ids: list[int]
    event_date: date
    reporting_month_id: int | None
    reporting_month_status: str | None
    scope: Literal["portfolio", "account"]
    account_id: int | None
    performance_currency: str
    material_signature: str | None
    pre_external_flow: list[CaptureSideOut]
    post_external_flow: list[CaptureSideOut]
    pre_state: str
    post_state: str
    missing_relations: list[str]
    reason_codes: list[str]
    capture_capability: str | None
    blocked_reason: str | None
    form_token: str | None


class CapturedObservationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    relation: str
    observed_date: date
    material_signature: str


class ValuationCaptureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    scope: Literal["portfolio", "account"]
    account_id: int | None
    start_date: date
    end_date: date
    performance_currency: str
    targets: list[CaptureTargetOut]
    readiness: PerformanceReadinessResponse
    captured: CapturedObservationOut | None = None


class CaptureContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["portfolio", "account"]
    account_id: int | None = None
    start_date: date
    end_date: date


class CaptureSubmission(CaptureContext):
    """One authoritative observed side; only source-backed values are accepted.

    The supported #533 adapter has no observation correction path, so it
    persists only ``complete``/``exact`` evidence in the target performance
    currency.  Incomplete, inexact or foreign-currency submissions are
    rejected before any mutation.
    """

    form_token: str = Field(min_length=1, max_length=128)
    external_flow_id: int | None = Field(default=None, gt=0)
    boundary_group_id: int | None = Field(default=None, gt=0)
    relation: Literal["pre_external_flow", "post_external_flow"]
    expected_material_signature: str = Field(min_length=64, max_length=64)
    total_value: str = Field(min_length=1, max_length=32)
    performance_currency: str = Field(min_length=3, max_length=3)
    coverage: Literal["complete"]
    quality: Literal["exact"]
    provenance_kind: str = Field(min_length=1, max_length=64)
    provenance_reference: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    attested: StrictBool

    @field_validator("total_value")
    @classmethod
    def validate_exact_amount(cls, value: str) -> str:
        try:
            decimal_value = Decimal(value)
        except DecimalException as error:
            raise ValueError("total_value must be a finite decimal string") from error
        if not decimal_value.is_finite():
            raise ValueError("total_value must be finite")
        if decimal_value < 0:
            raise ValueError("total_value must not be negative")
        scaled = decimal_value * Decimal(100)
        if scaled != scaled.to_integral_value():
            raise ValueError("total_value must have no more than two decimal places")
        return value

    @field_validator("performance_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("performance_currency must be a three-letter code")
        return normalized

    @field_validator("provenance_kind")
    @classmethod
    def validate_provenance_kind(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provenance_kind must not be empty")
        return value

    @model_validator(mode="after")
    def validate_target(self) -> "CaptureSubmission":
        if (self.external_flow_id is None) == (self.boundary_group_id is None):
            raise ValueError("exactly one external_flow_id or boundary_group_id is required")
        if self.attested is not True:
            raise ValueError("the observed value must be explicitly attested")
        return self


class _CaptureBinding(BaseModel):
    """Exact capture form identity; a token only replays one same target."""

    model_config = ConfigDict(frozen=True)

    scope: Literal["portfolio", "account"]
    account_id: int | None
    start_date: date
    end_date: date
    external_flow_id: int | None
    boundary_group_id: int | None
    expected_material_signature: str


class CaptureFormRegistry:
    """Bounded process-local single-use forms, not an audit log or a revision.

    Restart loses all forms (fail closed).  Restore admission changes the
    epoch and retires older forms.  A token is consumed even when the
    submission is later rejected, so an ambiguous outcome can never be
    replayed blindly; the caller rereads and re-attests instead.
    """

    def __init__(self) -> None:
        self.lock = Lock()
        self.tokens: dict[str, tuple[float, int, str]] = {}

    def issue(self, epoch: int, binding: _CaptureBinding) -> str:
        with self.lock:
            now = monotonic()
            self.tokens = {
                key: value
                for key, value in self.tokens.items()
                if value[0] > now and value[1] == epoch
            }
            if len(self.tokens) >= 1024:
                self.tokens.pop(next(iter(self.tokens)))
            token = token_urlsafe(32)
            self.tokens[token] = (now + 1800, epoch, binding.model_dump_json())
            return token

    def consume(self, token: str, epoch: int, binding: _CaptureBinding) -> None:
        with self.lock:
            entry = self.tokens.pop(token, None)
        if (
            entry is None
            or entry[0] <= monotonic()
            or entry[1] != epoch
            or entry[2] != binding.model_dump_json()
        ):
            raise ValueError(
                "Capture form expired, restored or already submitted; reread before saving"
            )


_registry_lock = Lock()


def _registry(request: Request) -> CaptureFormRegistry:
    with _registry_lock:
        if not hasattr(request.app.state, "valuation_capture_forms"):
            request.app.state.valuation_capture_forms = CaptureFormRegistry()
        return request.app.state.valuation_capture_forms


def _context(value: CaptureContext) -> CaptureContext:
    # Reject invalid scope/account combinations; never silently default one.
    _validate_request(
        scope=PerformanceScope(value.scope),
        account_id=value.account_id,
        start_date=value.start_date,
        end_date=value.end_date,
    )
    return CaptureContext(**{key: getattr(value, key) for key in CaptureContext.model_fields})


def _binding(value: CaptureSubmission) -> _CaptureBinding:
    return _CaptureBinding(
        scope=value.scope,
        account_id=value.account_id,
        start_date=value.start_date,
        end_date=value.end_date,
        external_flow_id=value.external_flow_id,
        boundary_group_id=value.boundary_group_id,
        expected_material_signature=value.expected_material_signature,
    )


def _side(side: CaptureSide) -> CaptureSideOut:
    return CaptureSideOut(
        id=side.id,
        relation=side.relation.value,
        observed_date=side.observed_date,
        total_value=ExactMoneyOut(
            amount=side.total_value.to_api(),
            currency=side.performance_currency,
        ),
        performance_currency=side.performance_currency,
        coverage=side.coverage.value,
        quality=side.quality.value,
        provenance_kind=side.provenance_kind,
        bound=side.bound,
    )


def _target(
    target: CaptureTarget,
    *,
    form_token: str | None,
) -> CaptureTargetOut:
    return CaptureTargetOut(
        boundary_group_id=target.boundary_group_id,
        flow_ids=list(target.flow_ids),
        event_date=target.event_date,
        reporting_month_id=target.reporting_month_id,
        reporting_month_status=target.reporting_month_status,
        scope=target.scope.value,
        account_id=target.account_id,
        performance_currency=target.performance_currency,
        material_signature=target.material_signature,
        pre_external_flow=[_side(side) for side in target.pre_sides],
        post_external_flow=[_side(side) for side in target.post_sides],
        pre_state=target.pre_state,
        post_state=target.post_state,
        missing_relations=[relation.value for relation in target.needs_capture],
        reason_codes=list(target.reason_codes),
        capture_capability=target.capture_capability,
        blocked_reason=target.blocked_reason,
        form_token=form_token,
    )


def _token_for(request: Request, context: CaptureContext, target: CaptureTarget) -> str | None:
    if target.capture_capability != "available" or target.material_signature is None:
        return None
    binding = _CaptureBinding(
        scope=context.scope,
        account_id=context.account_id,
        start_date=context.start_date,
        end_date=context.end_date,
        external_flow_id=target.flow_ids[0] if target.boundary_group_id is None else None,
        boundary_group_id=target.boundary_group_id,
        expected_material_signature=target.material_signature,
    )
    maintenance = _database_for_request(request).maintenance
    return _registry(request).issue(maintenance.form_epoch, binding)


def _response(
    request: Request,
    context: CaptureContext,
    projection: ValuationCaptureProjection,
    readiness: PerformanceReadinessResponse,
    *,
    captured: CapturedObservationOut | None = None,
) -> ValuationCaptureResponse:
    return ValuationCaptureResponse(
        scope=projection.scope.value,
        account_id=projection.account_id,
        start_date=projection.start_date,
        end_date=projection.end_date,
        performance_currency=projection.performance_currency,
        targets=[
            _target(target, form_token=_token_for(request, context, target))
            for target in projection.targets
        ],
        readiness=readiness,
        captured=captured,
    )


def _read(
    request: Request,
    session: Session,
    context: CaptureContext,
) -> ValuationCaptureResponse:
    with coherent_read_snapshot(session):
        if context.scope == "account" and session.get(Account, context.account_id) is None:
            raise HTTPException(404, "Account not found")
        projection = valuation_capture_projection_for_interval(
            session,
            start_date=context.start_date,
            end_date=context.end_date,
            scope=PerformanceScope(context.scope),
            account_id=context.account_id,
        )
        readiness = read_performance_readiness(
            request,
            start_date=context.start_date,
            end_date=context.end_date,
            scope=PerformanceScope(context.scope),
            account_id=context.account_id,
            session=session,
        )
        if not isinstance(readiness, PerformanceReadinessResponse):
            raise HTTPException(503, "Valuation capture/readiness read-back did not complete")
        return _response(request, context, projection, readiness)


@router.get("", response_model=ValuationCaptureResponse)
def read_valuation_captures(
    request: Request,
    start_date: date,
    end_date: date,
    scope: PerformanceScope = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
    session: Session = Depends(session_for_request),
) -> ValuationCaptureResponse:
    for name in ("start_date", "end_date", "scope", "account_id"):
        if len(request.query_params.getlist(name)) > 1:
            raise ValueError("Performance query parameters must not be repeated")
    context = _context(
        CaptureContext(
            scope=scope.value,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    )
    return _read(request, session, context)


@router.post("", response_model=ValuationCaptureResponse, responses={409: {"model": ErrorResponse}})
def capture_observed_valuation(
    payload: CaptureSubmission,
    request: Request,
    session: Session = Depends(session_for_request),
) -> ValuationCaptureResponse:
    context = _context(payload)
    binding = _binding(payload)
    saved_id: int
    try:
        _registry(request).consume(
            payload.form_token, _database_for_request(request).maintenance.form_epoch, binding
        )
        point = stage_observed_valuation_capture(
            session,
            scope=PerformanceScope(payload.scope),
            account_id=context.account_id,
            relation=payload.relation,
            expected_material_signature=payload.expected_material_signature,
            total_value=payload.total_value,
            performance_currency=payload.performance_currency,
            coverage=payload.coverage,
            quality=payload.quality,
            provenance_kind=payload.provenance_kind,
            provenance_reference=payload.provenance_reference,
            external_flow_id=payload.external_flow_id,
            boundary_group_id=payload.boundary_group_id,
            notes=payload.notes,
        )
        saved_id = point.id
        session.commit()
    except ValueError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    except Exception:
        session.rollback()
        raise

    # A commit acknowledgement alone is not a confirmed capture: reread the
    # capture targets and the canonical readiness in one committed snapshot.
    with coherent_read_snapshot(session):
        projection = valuation_capture_projection_for_interval(
            session,
            start_date=context.start_date,
            end_date=context.end_date,
            scope=PerformanceScope(context.scope),
            account_id=context.account_id,
        )
        target = next(
            (
                candidate
                for candidate in projection.targets
                if (
                    candidate.boundary_group_id == payload.boundary_group_id
                    if payload.boundary_group_id is not None
                    else candidate.boundary_group_id is None
                    and candidate.flow_ids == (payload.external_flow_id,)
                )
            ),
            None,
        )
        sides = [] if target is None else [*target.pre_sides, *target.post_sides]
        saved_side = next((side for side in sides if side.id == saved_id), None)
        if (
            target is None
            or saved_side is None
            or saved_side.relation.value != payload.relation
            or not saved_side.bound
            or target.material_signature != payload.expected_material_signature
        ):
            raise HTTPException(
                409,
                "Capture read-back did not confirm the stored observation; "
                "reread before another action",
            )
        readiness = read_performance_readiness(
            request,
            start_date=context.start_date,
            end_date=context.end_date,
            scope=PerformanceScope(context.scope),
            account_id=context.account_id,
            session=session,
        )
        if not isinstance(readiness, PerformanceReadinessResponse):
            raise HTTPException(503, "Valuation capture/readiness read-back did not complete")
        return _response(
            request,
            context,
            projection,
            readiness,
            captured=CapturedObservationOut(
                id=saved_side.id,
                relation=saved_side.relation.value,
                observed_date=saved_side.observed_date,
                material_signature=target.material_signature,
            ),
        )
