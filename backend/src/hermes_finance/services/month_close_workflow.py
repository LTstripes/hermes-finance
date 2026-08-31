"""Provider-free, read-only monthly close workflow assembly."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from hermes_finance.domain.month_close_workflow import (
    GuidedCloseAction,
    GuidedCloseActionId,
    GuidedCloseActionTarget,
    GuidedCloseApplicability,
    GuidedCloseCompletionBasis,
    GuidedCloseEvidenceScope,
    GuidedCloseGate,
    GuidedCloseStale,
    GuidedCloseStep,
    GuidedCloseStepId,
    GuidedCloseStepState,
    derive_step_state,
    recommended_step_id,
)
from hermes_finance.services.close_readiness import (
    CloseReadiness,
    CloseReadinessBackup,
    build_close_readiness,
)
from hermes_finance.services.freshness_provenance import (
    FreshnessFamily,
    FreshnessProvenanceSummary,
    FreshnessReasonCode,
    FreshnessSeverity,
    FreshnessStatus,
    build_freshness_provenance_summary,
)
from hermes_finance.services.reporting_months import get_reporting_month

WORKFLOW_CONTRACT_VERSION = "monthly_close_workflow_v1"

_STEP_DEFINITIONS = (
    (GuidedCloseStepId.MONTH_SETUP, "Открыть отчётный месяц"),
    (GuidedCloseStepId.ALFA_BASELINE, "Сверить состав портфеля Alfa"),
    (GuidedCloseStepId.MARKET_QUOTES, "Обновить рыночные цены"),
    (GuidedCloseStepId.ACTUAL_PAYOUTS, "Проверить фактические выплаты"),
    (GuidedCloseStepId.FUTURE_PAYOUTS, "Обновить будущие выплаты"),
    (GuidedCloseStepId.BROKER_RECONCILIATION, "Проверить портфель после обновлений"),
    (GuidedCloseStepId.READINESS, "Проверить качество данных и готовность"),
    (GuidedCloseStepId.FINAL_REVIEW_CLOSE, "Проверить итог и закрыть месяц"),
    (GuidedCloseStepId.NEXT_MONTH_OUTLOOK, "Что известно о следующем месяце"),
)

_ACTION_LABELS = {
    GuidedCloseActionId.SET_SNAPSHOT_DATE: "Указать дату снимка",
    GuidedCloseActionId.OPEN_ALFA_PREVIEW: "Получить данные Alfa PRO",
    GuidedCloseActionId.OPEN_QUOTE_PREVIEW: "Получить котировки",
    GuidedCloseActionId.CHOOSE_STATEMENT_FILE: "Выбрать PDF Alfa",
    GuidedCloseActionId.OPEN_PAYOUT_BATCH_PREVIEW: "Проверить все позиции T-Invest",
    GuidedCloseActionId.OPEN_RECONCILIATION_PREVIEW: "Проверить снимок Alfa",
    GuidedCloseActionId.OPEN_FRESHNESS: "Открыть свежесть и provenance",
    GuidedCloseActionId.OPEN_FINAL_REVIEW: "Перейти к итогам",
    GuidedCloseActionId.CONFIRM_CLOSE: "Закрыть месяц",
    GuidedCloseActionId.OPEN_CASH_FLOW_LADDER: "Открыть денежную лестницу",
}


def _action(action_id: GuidedCloseActionId, target: GuidedCloseActionTarget) -> GuidedCloseAction:
    return GuidedCloseAction(id=action_id, label=_ACTION_LABELS[action_id], target=target)


def _family(summary: FreshnessProvenanceSummary, family_id: str) -> FreshnessFamily:
    return next(family for family in summary.families if family.family_id.value == family_id)


def _family_summary(family: FreshnessFamily) -> dict[str, object]:
    return {
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


def _unavailable_evidence(reason_code: str) -> dict[str, object]:
    return {"available": False, "reason_code": reason_code}


def _step(
    *,
    step_id: GuidedCloseStepId,
    state: GuidedCloseStepState,
    applicability: GuidedCloseApplicability,
    gate: GuidedCloseGate,
    affects_close: bool,
    why: str,
    reason_codes: tuple[str, ...] = (),
    primary_action: GuidedCloseAction | None = None,
    completion_basis: GuidedCloseCompletionBasis | None = None,
    evidence_scope: GuidedCloseEvidenceScope = GuidedCloseEvidenceScope.NONE,
    evidence_summary: dict[str, object] | None = None,
    stale: GuidedCloseStale | None = None,
    diagnostics: dict[str, object] | None = None,
) -> GuidedCloseStep:
    title = dict(_STEP_DEFINITIONS)[step_id]
    return GuidedCloseStep(
        id=step_id,
        order=next(
            index
            for index, (candidate, _title) in enumerate(_STEP_DEFINITIONS, 1)
            if candidate is step_id
        ),
        title=title,
        state=state,
        applicability=applicability,
        gate=gate,
        affects_close=affects_close,
        why=why,
        reason_codes=reason_codes,
        primary_action=primary_action,
        completion_basis=completion_basis,
        evidence_scope=evidence_scope,
        evidence_summary=evidence_summary or {},
        stale=stale or GuidedCloseStale(),
        diagnostics=diagnostics or {},
    )


def _provider_step_read_only(
    *, step_id: GuidedCloseStepId, why: str, reason_code: str, action_id: GuidedCloseActionId
) -> GuidedCloseStep:
    return _step(
        step_id=step_id,
        state=GuidedCloseStepState.READY,
        applicability=GuidedCloseApplicability.CONDITIONAL,
        gate=GuidedCloseGate.OWNER_DECISION,
        affects_close=False,
        why=why,
        reason_codes=(reason_code,),
        primary_action=_action(action_id, GuidedCloseActionTarget.OPEN_PANEL),
        evidence_summary=_unavailable_evidence(reason_code),
    )


def _market_quote_step(summary: FreshnessProvenanceSummary) -> GuidedCloseStep:
    family = _family(summary, "market_quotes")
    coverage = family.coverage
    if coverage.row_count == 0:
        return _step(
            step_id=GuidedCloseStepId.MARKET_QUOTES,
            state=derive_step_state(not_applicable=True),
            applicability=GuidedCloseApplicability.NOT_APPLICABLE,
            gate=GuidedCloseGate.NONE,
            affects_close=False,
            why="В выбранном месяце нет локальных позиций для котировок.",
            reason_codes=("no_quote_eligible_positions",),
            evidence_summary={"available": True, "row_count": 0},
        )
    warning_codes = tuple(
        reason.code.value
        for reason in family.reasons
        if reason.severity is FreshnessSeverity.WARNING
    )
    has_manual_or_missing = coverage.manual_count > 0 or coverage.missing_count > 0
    complete = (
        coverage.provider_count > 0
        and coverage.current_count == coverage.provider_count
        and coverage.stale_count == 0
        and coverage.unavailable_count == 0
        and coverage.unknown_count == 0
        and coverage.missing_count == 0
        and not has_manual_or_missing
    )
    stale_or_partial = (
        bool(warning_codes)
        or has_manual_or_missing
        or family.status
        in {
            FreshnessStatus.STALE,
            FreshnessStatus.MIXED,
            FreshnessStatus.UNAVAILABLE,
        }
    )
    reason_codes = warning_codes or (
        (FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP.value,)
        if has_manual_or_missing
        else ("quote_not_applied",)
    )
    return _step(
        step_id=GuidedCloseStepId.MARKET_QUOTES,
        state=derive_step_state(stale_or_partial=stale_or_partial, completed=complete, ready=True),
        applicability=GuidedCloseApplicability.CONDITIONAL,
        gate=GuidedCloseGate.OWNER_DECISION,
        affects_close=False,
        why=(
            "Для части позиций нужна проверка рыночных цен."
            if stale_or_partial
            else "Проверка котировок доступна явным действием владельца."
        ),
        reason_codes=reason_codes,
        primary_action=_action(
            GuidedCloseActionId.OPEN_QUOTE_PREVIEW, GuidedCloseActionTarget.OPEN_PANEL
        ),
        completion_basis=GuidedCloseCompletionBasis.BACKEND_READ if complete else None,
        evidence_scope=(
            GuidedCloseEvidenceScope.FULL_CURRENT_LOCAL_SCOPE
            if complete
            else GuidedCloseEvidenceScope.NONE
        ),
        evidence_summary={"available": True, **_family_summary(family)},
        stale=GuidedCloseStale(is_stale=stale_or_partial, reason_codes=reason_codes),
    )


def _readiness_step(readiness: CloseReadiness) -> GuidedCloseStep:
    blockers = tuple(item.code for item in readiness.items if item.severity.value == "hard_blocker")
    warnings = tuple(item.code for item in readiness.items if item.severity.value == "warning")
    if blockers:
        action = (
            _action(GuidedCloseActionId.SET_SNAPSHOT_DATE, GuidedCloseActionTarget.OPEN_PANEL)
            if "snapshot_date_required" in blockers
            else _action(GuidedCloseActionId.OPEN_FRESHNESS, GuidedCloseActionTarget.INTERNAL_ROUTE)
        )
        return _step(
            step_id=GuidedCloseStepId.READINESS,
            state=derive_step_state(hard_blocked=True),
            applicability=GuidedCloseApplicability.MANDATORY,
            gate=GuidedCloseGate.MUST_RESOLVE,
            affects_close=True,
            why="Есть hard blocker из действующего Close Cockpit.",
            reason_codes=blockers,
            primary_action=action,
            diagnostics={"warning_count": len(warnings)},
        )
    if warnings:
        return _step(
            step_id=GuidedCloseStepId.READINESS,
            state=derive_step_state(stale_or_partial=True),
            applicability=GuidedCloseApplicability.MANDATORY,
            gate=GuidedCloseGate.ADVISORY,
            affects_close=False,
            why="Можно закрыть с предупреждениями из действующего Close Cockpit.",
            reason_codes=warnings,
            primary_action=_action(
                GuidedCloseActionId.OPEN_FRESHNESS, GuidedCloseActionTarget.INTERNAL_ROUTE
            ),
            completion_basis=GuidedCloseCompletionBasis.BACKEND_READ,
            diagnostics={"warning_count": len(warnings)},
        )
    return _step(
        step_id=GuidedCloseStepId.READINESS,
        state=derive_step_state(completed=True),
        applicability=GuidedCloseApplicability.MANDATORY,
        gate=GuidedCloseGate.NONE,
        affects_close=False,
        why="Close Cockpit не нашёл hard blockers или предупреждений.",
        completion_basis=GuidedCloseCompletionBasis.BACKEND_READ,
        diagnostics={"warning_count": 0},
    )


def _closed_read_only_step(step_id: GuidedCloseStepId) -> GuidedCloseStep:
    return _step(
        step_id=step_id,
        state=GuidedCloseStepState.NOT_STARTED,
        applicability=GuidedCloseApplicability.CONDITIONAL,
        gate=GuidedCloseGate.NONE,
        affects_close=False,
        why="Месяц закрыт и доступен только для чтения; для нового действия сначала нужно явное открытие.",
        reason_codes=("month_closed_read_only",),
        evidence_summary=_unavailable_evidence("month_closed_read_only"),
    )


def build_month_close_workflow(
    session: Session,
    month_id: int,
    *,
    today: date,
    generated_at: datetime | None = None,
    latest_backup: CloseReadinessBackup | None = None,
) -> tuple[object, ...]:
    """Build the provider-free workflow read model for one requested month.

    The tuple contains ``(month, readiness, freshness, steps, recommended_id,
    generated_at)`` to keep the domain values easy to inspect at the API boundary.
    ``get_reporting_month`` intentionally receives the requested ID directly; no
    newest-month fallback is permitted.
    """

    with session.no_autoflush:
        month = get_reporting_month(session, month_id)
        clock = generated_at or datetime.now(UTC)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=UTC)
        freshness = (
            build_freshness_provenance_summary(session, month.id, today=today, generated_at=clock)
            if month.snapshot_date is not None
            else None
        )
        readiness = build_close_readiness(
            session,
            month.id,
            today=today,
            latest_backup=latest_backup,
            freshness_summary=freshness,
        )
        closed = month.status == "closed"
        if closed:
            first = _step(
                step_id=GuidedCloseStepId.MONTH_SETUP,
                state=derive_step_state(completed=True),
                applicability=GuidedCloseApplicability.MANDATORY,
                gate=GuidedCloseGate.NONE,
                affects_close=False,
                why="Месяц уже закрыт; открыт режим только для чтения.",
                reason_codes=("month_closed_read_only",),
                completion_basis=GuidedCloseCompletionBasis.MONTH_CLOSED,
            )
            steps = (
                first,
                *(_closed_read_only_step(step_id) for step_id, _title in _STEP_DEFINITIONS[1:7]),
                _step(
                    step_id=GuidedCloseStepId.READINESS,
                    state=derive_step_state(completed=True),
                    applicability=GuidedCloseApplicability.MANDATORY,
                    gate=GuidedCloseGate.NONE,
                    affects_close=False,
                    why="Закрытый месяц сохранён; Close Cockpit доступен для просмотра.",
                    reason_codes=("month_closed_read_only",),
                    completion_basis=GuidedCloseCompletionBasis.MONTH_CLOSED,
                ),
                _step(
                    step_id=GuidedCloseStepId.FINAL_REVIEW_CLOSE,
                    state=derive_step_state(completed=True),
                    applicability=GuidedCloseApplicability.MANDATORY,
                    gate=GuidedCloseGate.NONE,
                    affects_close=False,
                    why="Месяц закрыт явной командой Close.",
                    reason_codes=("month_closed_read_only",),
                    completion_basis=GuidedCloseCompletionBasis.MONTH_CLOSED,
                ),
                _step(
                    step_id=GuidedCloseStepId.NEXT_MONTH_OUTLOOK,
                    state=derive_step_state(not_applicable=True),
                    applicability=GuidedCloseApplicability.NOT_APPLICABLE,
                    gate=GuidedCloseGate.NONE,
                    affects_close=False,
                    why="Постзакрывающий outlook будет собран отдельной read-only композицией.",
                    reason_codes=("outlook_section_unavailable",),
                    evidence_summary=_unavailable_evidence("outlook_section_unavailable"),
                ),
            )
        else:
            month_blocked = month.snapshot_date is None
            month_step = _step(
                step_id=GuidedCloseStepId.MONTH_SETUP,
                state=derive_step_state(hard_blocked=month_blocked, completed=not month_blocked),
                applicability=GuidedCloseApplicability.MANDATORY,
                gate=GuidedCloseGate.MUST_RESOLVE if month_blocked else GuidedCloseGate.NONE,
                affects_close=month_blocked,
                why=(
                    "Перед закрытием нужно указать дату снимка."
                    if month_blocked
                    else "Выбранный черновик и его дата снимка доступны."
                ),
                reason_codes=("snapshot_date_required",) if month_blocked else (),
                primary_action=(
                    _action(
                        GuidedCloseActionId.SET_SNAPSHOT_DATE, GuidedCloseActionTarget.OPEN_PANEL
                    )
                    if month_blocked
                    else None
                ),
                completion_basis=None if month_blocked else GuidedCloseCompletionBasis.DOMAIN_FACT,
            )
            provider_steps = (
                _provider_step_read_only(
                    step_id=GuidedCloseStepId.ALFA_BASELINE,
                    why=(
                        "Сохранённого подтверждения Alfa в core-контракте нет; "
                        "проверка запускается только явным действием."
                    ),
                    reason_code="baseline_not_applied",
                    action_id=GuidedCloseActionId.OPEN_ALFA_PREVIEW,
                ),
                (
                    _market_quote_step(freshness)
                    if freshness is not None
                    else _provider_step_read_only(
                        step_id=GuidedCloseStepId.MARKET_QUOTES,
                        why="Без даты снимка проверка котировок недоступна.",
                        reason_code="snapshot_date_required",
                        action_id=GuidedCloseActionId.OPEN_QUOTE_PREVIEW,
                    )
                ),
                _provider_step_read_only(
                    step_id=GuidedCloseStepId.ACTUAL_PAYOUTS,
                    why="Фактические выплаты проверяются через отдельный явный PDF workflow.",
                    reason_code="statement_not_imported",
                    action_id=GuidedCloseActionId.CHOOSE_STATEMENT_FILE,
                ),
                _provider_step_read_only(
                    step_id=GuidedCloseStepId.FUTURE_PAYOUTS,
                    why="Будущие выплаты проверяются отдельным явным T-Invest workflow.",
                    reason_code="payout_zero_result_not_persisted",
                    action_id=GuidedCloseActionId.OPEN_PAYOUT_BATCH_PREVIEW,
                ),
                _provider_step_read_only(
                    step_id=GuidedCloseStepId.BROKER_RECONCILIATION,
                    why=(
                        "Проверка Alfa доступна только по явной команде и не сохраняется "
                        "этим read model."
                    ),
                    reason_code="reconciliation_not_run",
                    action_id=GuidedCloseActionId.OPEN_RECONCILIATION_PREVIEW,
                ),
            )
            steps = (
                month_step,
                *provider_steps,
                _readiness_step(readiness),
                _step(
                    step_id=GuidedCloseStepId.FINAL_REVIEW_CLOSE,
                    state=derive_step_state(
                        hard_blocked=bool(
                            any(item.severity.value == "hard_blocker" for item in readiness.items)
                        ),
                        stale_or_partial=bool(
                            any(item.severity.value == "warning" for item in readiness.items)
                        ),
                        ready=not any(
                            item.severity.value == "hard_blocker" for item in readiness.items
                        ),
                    ),
                    applicability=GuidedCloseApplicability.MANDATORY,
                    gate=GuidedCloseGate.MUST_RESOLVE
                    if any(item.severity.value == "hard_blocker" for item in readiness.items)
                    else GuidedCloseGate.OWNER_DECISION,
                    affects_close=any(
                        item.severity.value == "hard_blocker" for item in readiness.items
                    ),
                    why="Итоговая проверка завершится только явной командой Close.",
                    reason_codes=tuple(
                        item.code
                        for item in readiness.items
                        if item.severity.value in {"hard_blocker", "warning"}
                    ),
                    primary_action=_action(
                        GuidedCloseActionId.CONFIRM_CLOSE,
                        GuidedCloseActionTarget.CONFIRM_CLOSE,
                    ),
                    evidence_summary={
                        "available": False,
                        "reason_code": "final_review_not_in_core",
                    },
                ),
                _step(
                    step_id=GuidedCloseStepId.NEXT_MONTH_OUTLOOK,
                    state=derive_step_state(not_applicable=True),
                    applicability=GuidedCloseApplicability.NOT_APPLICABLE,
                    gate=GuidedCloseGate.NONE,
                    affects_close=False,
                    why=(
                        "Outlook появляется только после закрытия и отдельной композиции "
                        "известных событий."
                    ),
                    reason_codes=("outlook_not_available_until_closed",),
                    evidence_summary=_unavailable_evidence("outlook_not_available_until_closed"),
                ),
            )
        steps = tuple(steps)
        return month, readiness, freshness, steps, recommended_step_id(steps), clock
