"""Versioned HTTP boundary for the provider-free monthly close workflow."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.close_readiness import _latest_backup
from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import _database_for_request, session_for_request
from hermes_finance.database import Database
from hermes_finance.domain.month_close_workflow import (
    GuidedCloseAction,
    GuidedCloseStep,
    GuidedCloseStepId,
)
from hermes_finance.services.close_readiness import CloseReadiness
from hermes_finance.services.freshness_provenance import FreshnessProvenanceSummary
from hermes_finance.services.month_close_workflow import (
    WORKFLOW_CONTRACT_VERSION,
    build_month_close_workflow,
)

router = APIRouter(prefix="/api/months", tags=["month-close-workflow"])


class WorkflowActionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    target: str


class WorkflowStaleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_stale: bool
    reason_codes: list[str]


class GuidedCloseStepOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int
    title: str
    state: str
    applicability: str
    gate: str
    affects_close: bool
    why: str
    reason_codes: list[str]
    primary_action: WorkflowActionOut | None
    secondary_actions: list[WorkflowActionOut]
    completion_basis: str | None
    evidence_scope: str
    evidence_version: str | None
    evidence_summary: dict[str, object]
    stale: WorkflowStaleOut
    diagnostics: dict[str, object]


class WorkflowMonthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    year: int
    month: int
    status: str
    snapshot_date: date | None
    source: str


class WorkflowProgressOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed_or_skipped: int
    total_applicable: int


class WorkflowReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_close: bool
    hard_blocker_count: int
    warning_count: int
    reason_codes: list[str]


class WorkflowFreshnessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    evaluated_on: date | None
    quote_valuation_target_date: date | None
    families: list[dict[str, object]]
    reason_codes: list[str]


class WorkflowSectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason_code: str | None = None


class WorkflowLinksOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    close_readiness: str
    freshness: str


class GuidedCloseWorkflowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["monthly_close_workflow_v1"]
    generated_at: datetime
    month: WorkflowMonthOut
    recommended_step_id: str | None
    progress: WorkflowProgressOut
    steps: list[GuidedCloseStepOut]
    readiness: WorkflowReadinessOut
    freshness: WorkflowFreshnessOut
    final_review: WorkflowSectionOut
    outlook: WorkflowSectionOut | None
    links: WorkflowLinksOut


def _action_out(action: GuidedCloseAction | None) -> WorkflowActionOut | None:
    if action is None:
        return None
    return WorkflowActionOut(id=action.id.value, label=action.label, target=action.target.value)


def _step_out(step: GuidedCloseStep) -> GuidedCloseStepOut:
    return GuidedCloseStepOut(
        id=step.id.value,
        order=step.order,
        title=step.title,
        state=step.state.value,
        applicability=step.applicability.value,
        gate=step.gate.value,
        affects_close=step.affects_close,
        why=step.why,
        reason_codes=list(step.reason_codes),
        primary_action=_action_out(step.primary_action),
        secondary_actions=[_action_out(action) for action in step.secondary_actions if action],
        completion_basis=step.completion_basis.value if step.completion_basis else None,
        evidence_scope=step.evidence_scope.value,
        evidence_version=step.evidence_version,
        evidence_summary=step.evidence_summary,
        stale=WorkflowStaleOut(
            is_stale=step.stale.is_stale, reason_codes=list(step.stale.reason_codes)
        ),
        diagnostics=step.diagnostics,
    )


def _readiness_out(readiness: CloseReadiness) -> WorkflowReadinessOut:
    blockers = [item for item in readiness.items if item.severity.value == "hard_blocker"]
    warnings = [item for item in readiness.items if item.severity.value == "warning"]
    return WorkflowReadinessOut(
        can_close=readiness.can_close,
        hard_blocker_count=len(blockers),
        warning_count=len(warnings),
        reason_codes=[item.code for item in (*blockers, *warnings)],
    )


def _freshness_out(summary: FreshnessProvenanceSummary | None) -> WorkflowFreshnessOut:
    if summary is None:
        return WorkflowFreshnessOut(
            available=False,
            evaluated_on=None,
            quote_valuation_target_date=None,
            families=[],
            reason_codes=["snapshot_date_required"],
        )
    return WorkflowFreshnessOut(
        available=True,
        evaluated_on=summary.evaluated_on,
        quote_valuation_target_date=summary.quote_valuation_target_date,
        families=[
            {
                "family_id": family.family_id.value,
                "title": family.title,
                "status": family.status.value,
                "coverage": {
                    "row_count": family.coverage.row_count,
                    "current_count": family.coverage.current_count,
                    "stale_count": family.coverage.stale_count,
                    "unavailable_count": family.coverage.unavailable_count,
                    "unknown_count": family.coverage.unknown_count,
                    "missing_count": family.coverage.missing_count,
                    "manual_count": family.coverage.manual_count,
                    "provider_count": family.coverage.provider_count,
                },
                "reason_codes": [reason.code.value for reason in family.reasons],
            }
            for family in summary.families
        ],
        reason_codes=[reason.code.value for reason in summary.reasons],
    )


@router.get("/{month_id}/close-workflow", response_model=GuidedCloseWorkflowOut)
def get_month_close_workflow(
    month_id: int,
    request: Request,
    session: Session = Depends(session_for_request),
    database: Database = Depends(_database_for_request),
) -> GuidedCloseWorkflowOut:
    clock = getattr(request.app.state, "freshness_generated_at", None)
    generated_at = clock() if callable(clock) else datetime.now(UTC)
    today = moscow_today(request)
    month, readiness, freshness, steps, recommended, generated = build_month_close_workflow(
        session,
        month_id,
        today=today,
        generated_at=generated_at,
        latest_backup=_latest_backup(database),
    )
    completed_or_skipped = sum(
        step.state.value in {"completed", "skipped"}
        for step in steps
        if step.applicability.value != "not_applicable"
    )
    total_applicable = sum(step.applicability.value != "not_applicable" for step in steps)
    return GuidedCloseWorkflowOut(
        contract_version=WORKFLOW_CONTRACT_VERSION,
        generated_at=generated,
        month=WorkflowMonthOut(
            id=month.id,
            year=month.year,
            month=month.month,
            status=month.status,
            snapshot_date=month.snapshot_date,
            source=month.source,
        ),
        recommended_step_id=(
            recommended.value if isinstance(recommended, GuidedCloseStepId) else None
        ),
        progress=WorkflowProgressOut(
            completed_or_skipped=completed_or_skipped, total_applicable=total_applicable
        ),
        steps=[_step_out(step) for step in steps],
        readiness=_readiness_out(readiness),
        freshness=_freshness_out(freshness),
        final_review=WorkflowSectionOut(available=False, reason_code="final_review_not_in_core"),
        outlook=(
            WorkflowSectionOut(available=False, reason_code="outlook_section_unavailable")
            if month.status == "closed"
            else None
        ),
        links=WorkflowLinksOut(
            month=f"/months/{month.id}",
            close_readiness=f"/api/months/{month.id}/close-readiness",
            freshness=f"/api/months/{month.id}/freshness-provenance",
        ),
    )
