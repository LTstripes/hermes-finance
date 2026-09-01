"""Provider-free, read-only monthly close workflow assembly."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.month_close_workflow import (
    GuidedCloseAction,
    GuidedCloseActionId,
    GuidedCloseActionTarget,
    GuidedCloseApplicability,
    GuidedCloseCompletionBasis,
    GuidedCloseEvidenceScope,
    GuidedCloseGate,
    GuidedCloseReasonCode,
    GuidedCloseStale,
    GuidedCloseStep,
    GuidedCloseStepId,
    GuidedCloseStepState,
    derive_step_state,
    recommended_step_id,
)
from hermes_finance.domain.monthly_summary import MonthlySummaryResult
from hermes_finance.domain.values import RubleAmount
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    AppliedStatementEvent,
    AppliedStatementEventRevision,
    BrokerBaselineApply,
    BrokerBaselineApplyItem,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpectedCashFlow,
    ExpenseEntry,
    IncomeEntry,
    InstrumentMarketMapping,
    InvestmentCashFlow,
    MonthlyComment,
    PositionQuoteProvenance,
    PositionSnapshot,
    PropertySnapshot,
    SavingAllocation,
)
from hermes_finance.services.applied_statement_events import StatementLinkMode
from hermes_finance.services.cash import total_cash
from hermes_finance.services.cash_flow_ladder import (
    CashFlowLadderResult,
    build_cash_flow_ladder,
)
from hermes_finance.services.close_readiness import (
    CloseReadiness,
    CloseReadinessBackup,
    build_close_readiness,
)
from hermes_finance.services.dashboard import DashboardResult, build_dashboard
from hermes_finance.services.debts import total_debts
from hermes_finance.services.freshness_provenance import (
    PROVIDER_PRICE_SOURCES,
    FreshnessFamily,
    FreshnessProvenanceSummary,
    FreshnessReasonCode,
    FreshnessSeverity,
    FreshnessStatus,
    build_freshness_provenance_summary,
)
from hermes_finance.services.monthly_summary import monthly_summary
from hermes_finance.services.payout_preview import _manual_candidates_for_applied
from hermes_finance.services.properties import total_mortgage_balance, total_property_value
from hermes_finance.services.reporting_months import get_reporting_month
from hermes_finance.statement_import.dto import ALFA_DEPOSITORY_INCOME_PROVIDER

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
    GuidedCloseActionId.CLONE_NEXT_MONTH: "Создать следующий месяц",
}


@dataclass(frozen=True, slots=True)
class FinalMonthReview:
    """Read-only composition of the final review's existing authorities."""

    summary: MonthlySummaryResult
    dashboard: DashboardResult | None
    cash_flow_ladder: CashFlowLadderResult | None
    readiness: CloseReadiness
    freshness: FreshnessProvenanceSummary | None
    provider_summary: tuple[dict[str, object], ...]
    reconciliation_availability: dict[str, object]
    manual_review_cards: tuple[dict[str, object], ...]
    manual_attention: tuple[dict[str, object], ...]
    evidence_version: str


@dataclass(frozen=True, slots=True)
class NextMonthOutlook:
    """Closed-source, dated-facts-only outlook composition."""

    available: bool
    reason_code: str | None
    source_month: object
    cash_flow_ladder: CashFlowLadderResult | None
    next_month: tuple[int, int] | None
    known_event_count: int
    evidence_version: str | None


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


def _unique_reason_codes(codes: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


def _selected_evidence_summary(**counts: int) -> dict[str, object]:
    return {
        "available": True,
        "coverage_scope": GuidedCloseEvidenceScope.SELECTED_ROWS_ONLY.value,
        **counts,
    }


def _latest_baseline_apply(session: Session, month_id: int) -> BrokerBaselineApply | None:
    return session.scalar(
        select(BrokerBaselineApply)
        .where(BrokerBaselineApply.reporting_month_id == month_id)
        .order_by(BrokerBaselineApply.confirmed_at.desc(), BrokerBaselineApply.id.desc())
    )


def _alfa_baseline_step(session: Session, month: object) -> GuidedCloseStep:
    if getattr(month, "snapshot_date") is None:
        return _provider_step_read_only(
            step_id=GuidedCloseStepId.ALFA_BASELINE,
            why="Без даты снимка нельзя проверить сохранённое подтверждение Alfa.",
            reason_code=GuidedCloseReasonCode.SNAPSHOT_DATE_REQUIRED.value,
            action_id=GuidedCloseActionId.OPEN_ALFA_PREVIEW,
        )

    applied = _latest_baseline_apply(session, getattr(month, "id"))
    if applied is None:
        return _provider_step_read_only(
            step_id=GuidedCloseStepId.ALFA_BASELINE,
            why=(
                "Сохранённого подтверждения Alfa в core-контракте нет; "
                "проверка запускается только явным действием."
            ),
            reason_code=GuidedCloseReasonCode.BASELINE_NOT_APPLIED.value,
            action_id=GuidedCloseActionId.OPEN_ALFA_PREVIEW,
        )

    items = list(
        session.scalars(
            select(BrokerBaselineApplyItem)
            .where(
                BrokerBaselineApplyItem.reporting_month_id == getattr(month, "id"),
                BrokerBaselineApplyItem.baseline_apply_id == applied.id,
            )
            .order_by(BrokerBaselineApplyItem.id)
        )
    )
    if not items:
        return _step(
            step_id=GuidedCloseStepId.ALFA_BASELINE,
            state=GuidedCloseStepState.READY,
            applicability=GuidedCloseApplicability.CONDITIONAL,
            gate=GuidedCloseGate.OWNER_DECISION,
            affects_close=False,
            why="Подтверждение Alfa не содержит сохранённых выбранных позиций.",
            reason_codes=(GuidedCloseReasonCode.BASELINE_COVERAGE_NOT_PERSISTED.value,),
            primary_action=_action(
                GuidedCloseActionId.OPEN_ALFA_PREVIEW, GuidedCloseActionTarget.OPEN_PANEL
            ),
            evidence_summary=_unavailable_evidence(
                GuidedCloseReasonCode.BASELINE_COVERAGE_NOT_PERSISTED.value
            ),
        )

    snapshot_ids = {item.position_snapshot_id for item in items}
    snapshots = {
        snapshot.id: snapshot
        for snapshot in session.scalars(
            select(PositionSnapshot).where(PositionSnapshot.id.in_(snapshot_ids))
        )
    }
    position_missing = 0
    quantity_changed = 0
    for item in items:
        snapshot = snapshots.get(item.position_snapshot_id)
        if snapshot is None or snapshot.reporting_month_id != getattr(month, "id"):
            position_missing += 1
        elif snapshot.quantity != item.quantity:
            quantity_changed += 1

    date_changed = applied.baseline_date != getattr(month, "snapshot_date")
    stale_count = len(items) if date_changed else position_missing + quantity_changed
    matching_count = len(items) - stale_count
    reason_codes: list[str] = []
    if position_missing:
        reason_codes.append(GuidedCloseReasonCode.BASELINE_POSITION_MISSING.value)
    if quantity_changed:
        reason_codes.append(GuidedCloseReasonCode.BASELINE_QUANTITY_CHANGED.value)
    if date_changed:
        reason_codes.append(GuidedCloseReasonCode.BASELINE_DATE_CHANGED.value)
    reason_tuple = _unique_reason_codes(reason_codes)
    stale = bool(reason_tuple)
    return _step(
        step_id=GuidedCloseStepId.ALFA_BASELINE,
        state=derive_step_state(stale_or_partial=stale, completed=not stale),
        applicability=GuidedCloseApplicability.CONDITIONAL,
        gate=GuidedCloseGate.OWNER_DECISION,
        affects_close=False,
        why=(
            "Сохранённое выбранное подтверждение Alfa больше не совпадает с текущим месяцем "
            "или позициями."
            if stale
            else "Сохранены выбранные позиции Alfa; это не подтверждение полного покрытия провайдера."
        ),
        reason_codes=(
            reason_tuple if stale else (GuidedCloseReasonCode.BASELINE_SELECTED_ROWS_PRESENT.value,)
        ),
        primary_action=_action(
            GuidedCloseActionId.OPEN_ALFA_PREVIEW, GuidedCloseActionTarget.OPEN_PANEL
        ),
        completion_basis=GuidedCloseCompletionBasis.DOMAIN_FACT if not stale else None,
        evidence_scope=GuidedCloseEvidenceScope.SELECTED_ROWS_ONLY,
        evidence_summary=_selected_evidence_summary(
            selected_count=len(items),
            matching_count=matching_count,
            stale_count=stale_count,
        ),
        stale=GuidedCloseStale(is_stale=stale, reason_codes=reason_tuple),
    )


def _latest_statement_revisions(
    session: Session, event_ids: set[int]
) -> dict[int, AppliedStatementEventRevision]:
    if not event_ids:
        return {}
    latest: dict[int, AppliedStatementEventRevision] = {}
    revisions = session.scalars(
        select(AppliedStatementEventRevision)
        .where(AppliedStatementEventRevision.applied_statement_event_id.in_(event_ids))
        .order_by(AppliedStatementEventRevision.id)
    )
    for revision in revisions:
        latest[revision.applied_statement_event_id] = revision
    return latest


def _statement_flow_matches_accepted(
    *,
    event: AppliedStatementEvent,
    flow: InvestmentCashFlow | None,
    accepted: AppliedStatementEventRevision | None,
    month: object,
) -> bool:
    if (
        flow is None
        or accepted is None
        or event.investment_cash_flow_id is None
        or flow.id != event.investment_cash_flow_id
        or (accepted.event_date.year, accepted.event_date.month)
        != (getattr(month, "year"), getattr(month, "month"))
    ):
        return False
    expected_tax = accepted.tax_amount_kopecks if accepted.tax_available else 0
    if (
        flow.reporting_month_id != getattr(month, "id")
        or flow.account_id != event.account_id
        or flow.instrument_id != event.instrument_id
        or flow.flow_type != event.event_kind
        or flow.event_date != accepted.event_date
        or flow.gross_amount_kopecks != accepted.gross_amount_kopecks
        or flow.tax_amount_kopecks != expected_tax
        or flow.commission_amount_kopecks != 0
        or flow.net_amount_kopecks != accepted.net_amount_kopecks
        or flow.currency != accepted.net_currency
    ):
        return False
    try:
        link_mode = StatementLinkMode(event.link_mode)
    except ValueError:
        return False
    return (
        link_mode is not StatementLinkMode.STATEMENT_CREATED
        or flow.source == ALFA_DEPOSITORY_INCOME_PROVIDER
    )


def _retracted_statement_count(
    month: object,
    events: list[AppliedStatementEvent],
    revisions_by_event: dict[int, AppliedStatementEventRevision],
) -> int:
    count = 0
    for event in events:
        revision = revisions_by_event.get(event.id)
        event_date = revision.event_date if revision is not None else event.record_date
        if (event_date.year, event_date.month) == (getattr(month, "year"), getattr(month, "month")):
            count += 1
    return count


def _actual_payouts_step(session: Session, month: object) -> GuidedCloseStep:
    flows = list(
        session.scalars(
            select(InvestmentCashFlow).where(
                InvestmentCashFlow.reporting_month_id == getattr(month, "id")
            )
        )
    )
    flow_by_id = {flow.id: flow for flow in flows}
    active_events = (
        list(
            session.scalars(
                select(AppliedStatementEvent).where(
                    AppliedStatementEvent.status == "active",
                    AppliedStatementEvent.investment_cash_flow_id.in_(flow_by_id or {-1}),
                )
            )
        )
        if flow_by_id
        else []
    )
    retracted_events = list(
        session.scalars(
            select(AppliedStatementEvent).where(AppliedStatementEvent.status == "retracted")
        )
    )
    event_ids = {event.id for event in active_events} | {event.id for event in retracted_events}
    revisions_by_event = _latest_statement_revisions(session, event_ids)
    matching_count = sum(
        _statement_flow_matches_accepted(
            event=event,
            flow=flow_by_id.get(event.investment_cash_flow_id),
            accepted=revisions_by_event.get(event.id),
            month=month,
        )
        for event in active_events
    )
    changed_count = len(active_events) - matching_count
    retracted_count = _retracted_statement_count(month, retracted_events, revisions_by_event)
    if not active_events and not retracted_count:
        return _provider_step_read_only(
            step_id=GuidedCloseStepId.ACTUAL_PAYOUTS,
            why="Сохранённых активных выплат Alfa за выбранный месяц нет.",
            reason_code=GuidedCloseReasonCode.STATEMENT_NOT_IMPORTED.value,
            action_id=GuidedCloseActionId.CHOOSE_STATEMENT_FILE,
        )

    reason_codes: list[str] = []
    if changed_count:
        reason_codes.append(GuidedCloseReasonCode.STATEMENT_LINKED_FLOW_CHANGED.value)
    if retracted_count:
        reason_codes.append(GuidedCloseReasonCode.STATEMENT_ROWS_RETRACTED.value)
    reason_tuple = _unique_reason_codes(reason_codes)
    stale = bool(reason_tuple)
    return _step(
        step_id=GuidedCloseStepId.ACTUAL_PAYOUTS,
        state=derive_step_state(stale_or_partial=stale, completed=not stale),
        applicability=GuidedCloseApplicability.CONDITIONAL,
        gate=GuidedCloseGate.OWNER_DECISION,
        affects_close=False,
        why=(
            "Часть сохранённых выплат Alfa требует повторной проверки."
            if stale
            else "Сохранены активные выплаты Alfa и совпадающие связанные денежные потоки."
        ),
        reason_codes=(
            reason_tuple if stale else (GuidedCloseReasonCode.STATEMENT_ACTIVE_ROWS_PRESENT.value,)
        ),
        primary_action=_action(
            GuidedCloseActionId.CHOOSE_STATEMENT_FILE, GuidedCloseActionTarget.OPEN_PANEL
        ),
        completion_basis=GuidedCloseCompletionBasis.DOMAIN_FACT if not stale else None,
        evidence_scope=GuidedCloseEvidenceScope.SELECTED_ROWS_ONLY,
        evidence_summary=_selected_evidence_summary(
            selected_count=len(active_events),
            matching_count=matching_count,
            stale_count=changed_count,
            retracted_count=retracted_count,
        ),
        stale=GuidedCloseStale(is_stale=stale, reason_codes=reason_tuple),
    )


@dataclass(frozen=True, slots=True)
class _PayoutDependencyCounts:
    position_missing: int = 0
    quantity_changed: int = 0
    mapping_changed: int = 0
    reconciliation_changed: int = 0
    affected_payouts: int = 0

    @property
    def stale_count(self) -> int:
        return self.affected_payouts


def _future_payout_dependencies(
    session: Session,
    month: object,
    payouts: list[AppliedProviderPayout],
) -> _PayoutDependencyCounts:
    snapshots = list(
        session.scalars(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == getattr(month, "id")
            )
        )
    )
    snapshot_by_identity = {(row.account_id, row.instrument_id): row for row in snapshots}
    instrument_ids = {payout.instrument_id for payout in payouts} | {
        row.instrument_id for row in snapshots
    }
    mappings = {
        mapping.instrument_id: mapping
        for mapping in session.scalars(
            select(InstrumentMarketMapping).where(
                InstrumentMarketMapping.instrument_id.in_(instrument_ids or {-1})
            )
        )
    }
    position_missing = quantity_changed = mapping_changed = reconciliation_changed = 0
    affected_payout_ids: set[int] = set()
    for payout in payouts:
        snapshot = snapshot_by_identity.get((payout.account_id, payout.instrument_id))
        if snapshot is None or payout.source_position_snapshot_id != snapshot.id:
            position_missing += 1
            affected_payout_ids.add(payout.id)
        elif payout.quantity != snapshot.quantity:
            quantity_changed += 1
            affected_payout_ids.add(payout.id)
        mapping = mappings.get(payout.instrument_id)
        if snapshot is not None and (
            mapping is None
            or mapping.excluded
            or mapping.provider != payout.provider
            or mapping.provider_instrument_id != payout.provider_instrument_uid
        ):
            mapping_changed += 1
            affected_payout_ids.add(payout.id)

    payout_ids = {payout.id for payout in payouts}
    links = list(
        session.scalars(
            select(AppliedPayoutReconciliation).where(
                AppliedPayoutReconciliation.applied_payout_id.in_(payout_ids or {-1})
            )
        )
    )
    flow_ids = {link.expected_cash_flow_id for link in links}
    flows = {
        flow.id: flow
        for flow in session.scalars(
            select(ExpectedCashFlow).where(ExpectedCashFlow.id.in_(flow_ids or {-1}))
        )
    }
    manual_candidates_by_scope: dict[tuple[int, int | None], list[ExpectedCashFlow]] = {}
    manual_candidates = session.scalars(
        select(ExpectedCashFlow)
        .where(
            ExpectedCashFlow.reporting_month_id == getattr(month, "id"),
            ExpectedCashFlow.flow_type.in_(("coupon", "dividend", "redemption")),
        )
        .order_by(ExpectedCashFlow.expected_date, ExpectedCashFlow.id)
    )
    for flow in manual_candidates:
        manual_candidates_by_scope.setdefault((flow.account_id, flow.instrument_id), []).append(
            flow
        )
    manual_candidate_ids = {
        flow.id for candidates in manual_candidates_by_scope.values() for flow in candidates
    }
    payout_by_id = {payout.id: payout for payout in payouts}
    reconciliation_by_payout = {link.applied_payout_id: link for link in links}
    for link in links:
        payout = payout_by_id.get(link.applied_payout_id)
        flow = flows.get(link.expected_cash_flow_id)
        if (
            payout is None
            or flow is None
            or flow.reporting_month_id != getattr(month, "id")
            or flow.account_id != payout.account_id
            or flow.instrument_id != payout.instrument_id
            or flow.flow_type != payout.event_kind
        ):
            reconciliation_changed += 1
            if payout is not None:
                affected_payout_ids.add(payout.id)
    for payout in payouts:
        link = reconciliation_by_payout.get(payout.id)
        candidate_ids = _manual_candidates_for_applied(
            payout,
            manual_candidates_by_scope.get((payout.account_id, payout.instrument_id), []),
        )
        resolved_manual_id = (
            link.expected_cash_flow_id
            if link is not None and link.expected_cash_flow_id in manual_candidate_ids
            else None
        )
        if (
            (link is not None and link.expected_cash_flow_id not in candidate_ids)
            or any(candidate_id != resolved_manual_id for candidate_id in candidate_ids)
            or (link is None and bool(candidate_ids))
        ):
            reconciliation_changed += 1
            affected_payout_ids.add(payout.id)
    return _PayoutDependencyCounts(
        position_missing=position_missing,
        quantity_changed=quantity_changed,
        mapping_changed=mapping_changed,
        reconciliation_changed=reconciliation_changed,
        affected_payouts=len(affected_payout_ids),
    )


def _future_payouts_step(session: Session, month: object) -> GuidedCloseStep:
    snapshots = list(
        session.scalars(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == getattr(month, "id")
            )
        )
    )
    snapshot_instrument_ids = {snapshot.instrument_id for snapshot in snapshots}
    mappings = {
        mapping.instrument_id: mapping
        for mapping in session.scalars(
            select(InstrumentMarketMapping).where(
                InstrumentMarketMapping.instrument_id.in_(snapshot_instrument_ids or {-1})
            )
        )
    }
    eligible_count = sum(
        bool(
            (mapping := mappings.get(snapshot.instrument_id))
            and not mapping.excluded
            and mapping.provider == T_INVEST_PROVIDER
            and mapping.provider_instrument_id
        )
        for snapshot in snapshots
    )
    payouts = list(
        session.scalars(
            select(AppliedProviderPayout).where(
                AppliedProviderPayout.reporting_month_id == getattr(month, "id"),
                AppliedProviderPayout.provider == T_INVEST_PROVIDER,
                AppliedProviderPayout.lifecycle == "active",
            )
        )
    )
    if not payouts:
        explicitly_excluded_count = sum(
            bool(mapping := mappings.get(snapshot.instrument_id)) and mapping.excluded
            for snapshot in snapshots
        )
        if not snapshots or explicitly_excluded_count == len(snapshots):
            return _step(
                step_id=GuidedCloseStepId.FUTURE_PAYOUTS,
                state=derive_step_state(not_applicable=True),
                applicability=GuidedCloseApplicability.NOT_APPLICABLE,
                gate=GuidedCloseGate.NONE,
                affects_close=False,
                why="В выбранном месяце нет текущих позиций, eligible для T-Invest выплат.",
                reason_codes=(GuidedCloseReasonCode.NO_PAYOUT_ELIGIBLE_POSITIONS.value,),
                evidence_summary={
                    "available": True,
                    "current_position_count": len(snapshots),
                    "eligible_position_count": eligible_count,
                    "active_count": 0,
                },
            )
        if not eligible_count:
            return _step(
                step_id=GuidedCloseStepId.FUTURE_PAYOUTS,
                state=GuidedCloseStepState.WARNING,
                applicability=GuidedCloseApplicability.CONDITIONAL,
                gate=GuidedCloseGate.OWNER_DECISION,
                affects_close=False,
                why=(
                    "Текущие позиции есть, но mapping T-Invest не зафиксирован; "
                    "отсутствие строк не доказывает отсутствие выплат."
                ),
                reason_codes=(GuidedCloseReasonCode.NO_PAYOUT_ELIGIBLE_POSITIONS.value,),
                primary_action=_action(
                    GuidedCloseActionId.OPEN_PAYOUT_BATCH_PREVIEW,
                    GuidedCloseActionTarget.OPEN_PANEL,
                ),
                evidence_summary={
                    "available": False,
                    "reason_code": GuidedCloseReasonCode.NO_PAYOUT_ELIGIBLE_POSITIONS.value,
                    "current_position_count": len(snapshots),
                    "eligible_position_count": 0,
                    "active_count": 0,
                },
            )
        return _step(
            step_id=GuidedCloseStepId.FUTURE_PAYOUTS,
            state=GuidedCloseStepState.READY,
            applicability=GuidedCloseApplicability.CONDITIONAL,
            gate=GuidedCloseGate.OWNER_DECISION,
            affects_close=False,
            why="Зафиксированных результатов T-Invest нет; отсутствие строк не доказывает нулевые выплаты.",
            reason_codes=(GuidedCloseReasonCode.PAYOUT_ZERO_RESULT_NOT_PERSISTED.value,),
            primary_action=_action(
                GuidedCloseActionId.OPEN_PAYOUT_BATCH_PREVIEW, GuidedCloseActionTarget.OPEN_PANEL
            ),
            evidence_summary={
                "available": False,
                "reason_code": GuidedCloseReasonCode.PAYOUT_ZERO_RESULT_NOT_PERSISTED.value,
                "current_position_count": len(snapshots),
                "eligible_position_count": eligible_count,
                "active_count": 0,
            },
        )

    dependencies = _future_payout_dependencies(session, month, payouts)
    reason_codes: list[str] = []
    if dependencies.position_missing:
        reason_codes.append(GuidedCloseReasonCode.PAYOUT_POSITION_MISSING.value)
    if dependencies.quantity_changed:
        reason_codes.append(GuidedCloseReasonCode.PAYOUT_QUANTITY_CHANGED.value)
    if dependencies.mapping_changed:
        reason_codes.append(GuidedCloseReasonCode.PAYOUT_MAPPING_CHANGED.value)
    if dependencies.reconciliation_changed:
        reason_codes.append(GuidedCloseReasonCode.PAYOUT_RECONCILIATION_CHANGED.value)
    reason_tuple = _unique_reason_codes(reason_codes)
    stale = bool(reason_tuple)
    return _step(
        step_id=GuidedCloseStepId.FUTURE_PAYOUTS,
        state=derive_step_state(stale_or_partial=stale, completed=not stale),
        applicability=GuidedCloseApplicability.CONDITIONAL,
        gate=GuidedCloseGate.OWNER_DECISION,
        affects_close=False,
        why=(
            "Сохранённые выплаты T-Invest больше не полностью совпадают с текущими "
            "позициями или mapping/reconciliation зависимостями."
            if stale
            else "Сохранены выбранные выплаты T-Invest; это не подтверждение полного покрытия провайдера."
        ),
        reason_codes=(
            reason_tuple
            if stale
            else (GuidedCloseReasonCode.PROVIDER_PAYOUT_ACTIVE_ROWS_PRESENT.value,)
        ),
        primary_action=_action(
            GuidedCloseActionId.OPEN_PAYOUT_BATCH_PREVIEW, GuidedCloseActionTarget.OPEN_PANEL
        ),
        completion_basis=GuidedCloseCompletionBasis.DOMAIN_FACT if not stale else None,
        evidence_scope=GuidedCloseEvidenceScope.SELECTED_ROWS_ONLY,
        evidence_summary=_selected_evidence_summary(
            selected_count=len(payouts),
            matching_count=len(payouts) - dependencies.stale_count,
            stale_count=dependencies.stale_count,
            eligible_position_count=eligible_count,
        ),
        stale=GuidedCloseStale(is_stale=stale, reason_codes=reason_tuple),
    )


def _latest_quote_provenance_by_snapshot(
    session: Session, month_id: int
) -> dict[int, PositionQuoteProvenance]:
    latest: dict[int, PositionQuoteProvenance] = {}
    rows = session.scalars(
        select(PositionQuoteProvenance)
        .where(PositionQuoteProvenance.reporting_month_id == month_id)
        .order_by(
            PositionQuoteProvenance.position_snapshot_id,
            PositionQuoteProvenance.applied_at_utc.desc(),
            PositionQuoteProvenance.id.desc(),
        )
    )
    for row in rows:
        latest.setdefault(row.position_snapshot_id, row)
    return latest


def _quote_mapping_mismatch_count(session: Session, month_id: int) -> int:
    snapshots = list(
        session.scalars(
            select(PositionSnapshot).where(PositionSnapshot.reporting_month_id == month_id)
        )
    )
    if not snapshots:
        return 0
    mappings = {
        mapping.instrument_id: mapping
        for mapping in session.scalars(
            select(InstrumentMarketMapping).where(
                InstrumentMarketMapping.instrument_id.in_({row.instrument_id for row in snapshots})
            )
        )
    }
    provenance_by_snapshot = _latest_quote_provenance_by_snapshot(session, month_id)
    return sum(
        1
        for snapshot in snapshots
        if snapshot.price_source in PROVIDER_PRICE_SOURCES
        and (quote := provenance_by_snapshot.get(snapshot.id)) is not None
        and (
            (mapping := mappings.get(snapshot.instrument_id)) is None
            or mapping.excluded
            or mapping.provider != quote.provider
            or mapping.provider_instrument_id != quote.provider_instrument_id
            or mapping.provider_venue_id != quote.provider_venue_id
        )
    )


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
    secondary_actions: tuple[GuidedCloseAction, ...] = (),
    completion_basis: GuidedCloseCompletionBasis | None = None,
    evidence_scope: GuidedCloseEvidenceScope = GuidedCloseEvidenceScope.NONE,
    evidence_version: str | None = None,
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
        secondary_actions=secondary_actions,
        completion_basis=completion_basis,
        evidence_scope=evidence_scope,
        evidence_version=evidence_version,
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


def _market_quote_step(
    summary: FreshnessProvenanceSummary, *, session: Session, month_id: int
) -> GuidedCloseStep:
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
    mapping_mismatch_count = _quote_mapping_mismatch_count(session, month_id)
    warning_codes = tuple(
        reason.code.value
        for reason in family.reasons
        if reason.severity is FreshnessSeverity.WARNING
    )
    if mapping_mismatch_count:
        warning_codes = _unique_reason_codes(
            [*warning_codes, GuidedCloseReasonCode.QUOTE_MAPPING_MISSING.value]
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
        and mapping_mismatch_count == 0
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
        evidence_summary={
            "available": True,
            **_family_summary(family),
            "mapping_mismatch_count": mapping_mismatch_count,
        },
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


def _count_rows(session: Session, model: type[object], month_id: int) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(model.reporting_month_id == month_id)
        )
        or 0
    )


def _sum_rows(session: Session, model: type[object], column: object, month_id: int) -> RubleAmount:
    total = session.scalar(
        select(func.coalesce(func.sum(column), 0)).where(model.reporting_month_id == month_id)
    )
    return RubleAmount(int(total or 0))


def _manual_review_cards(
    session: Session, month: object, summary: MonthlySummaryResult
) -> tuple[dict[str, object], ...]:
    month_id = getattr(month, "id")
    cash_total = total_cash(session, month_id)
    deposit_rows = _count_rows(session, DepositSnapshot, month_id)
    deposit_balance = summary.liquid_capital.breakdown.deposits
    property_value = total_property_value(session, month_id)
    mortgage_balance = total_mortgage_balance(session, month_id)
    position_count = _count_rows(session, PositionSnapshot, month_id)
    manual_position_count = int(
        session.scalar(
            select(func.count())
            .select_from(PositionSnapshot)
            .where(
                PositionSnapshot.reporting_month_id == month_id,
                PositionSnapshot.price_source == "manual",
            )
        )
        or 0
    )
    cards = (
        {
            "id": "cash",
            "title": "Деньги сейчас",
            "available": True,
            "reason_code": None,
            "summary": {
                "cash_total": cash_total,
                "row_count": _count_rows(session, CashBalance, month_id),
            },
        },
        {
            "id": "deposits_savings",
            "title": "Вклады и накопления",
            "available": True,
            "reason_code": None,
            "summary": {
                "balance": deposit_balance,
                "deposit_row_count": deposit_rows,
                "actual_interest_received": _sum_rows(
                    session,
                    DepositSnapshot,
                    DepositSnapshot.actual_interest_received_kopecks,
                    month_id,
                ),
                "savings_allocations": summary.cash_balance.breakdown.saving_allocations,
            },
        },
        {
            "id": "debts_property",
            "title": "Долги и недвижимость",
            "available": True,
            "reason_code": None,
            "summary": {
                "debt_total": total_debts(session, month_id),
                "property_value": property_value,
                "mortgage_balance": mortgage_balance,
                "debt_row_count": _count_rows(session, Debt, month_id),
                "property_row_count": _count_rows(session, PropertySnapshot, month_id),
            },
        },
        {
            "id": "income_budget",
            "title": "Доходы и бюджет",
            "available": True,
            "reason_code": None,
            "summary": {
                "cash_balance": summary.cash_balance.total,
                "passive_income_actual": summary.passive_income_actual,
                "salary_actual_net": summary.salary_actual_net,
                "mandatory_expenses": summary.cash_balance.breakdown.mandatory_expenses,
                "income_row_count": _count_rows(session, IncomeEntry, month_id),
                "expense_row_count": _count_rows(session, ExpenseEntry, month_id),
                "saving_allocation_count": _count_rows(session, SavingAllocation, month_id),
            },
        },
        {
            "id": "investments_outside_integrations",
            "title": "Инвестиции вне интеграций",
            "available": bool(position_count),
            "reason_code": None if position_count else "no_position_snapshots",
            "summary": {
                "position_count": position_count,
                "market_value": summary.liquid_capital.breakdown.securities,
                "manual_price_count": manual_position_count,
                "actual_flow_count": _count_rows(session, InvestmentCashFlow, month_id),
                "future_flow_count": _count_rows(session, ExpectedCashFlow, month_id),
            },
        },
        {
            "id": "note",
            "title": "Заметка",
            "available": bool(_count_rows(session, MonthlyComment, month_id)),
            "reason_code": None
            if _count_rows(session, MonthlyComment, month_id)
            else "optional_empty",
            "summary": {"comment_count": _count_rows(session, MonthlyComment, month_id)},
        },
    )
    return cards


def _attention_card_id(code: str) -> str:
    if code == "snapshot_date_required" or code.startswith("salary"):
        return "income_budget"
    if code.startswith("quote") or code.startswith("payout") or code.startswith("statement"):
        return "investments_outside_integrations"
    if code.startswith("freshness"):
        return "investments_outside_integrations"
    return "income_budget"


def _manual_attention(readiness: CloseReadiness) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "card_id": _attention_card_id(item.code),
            "severity": item.severity.value,
            "code": item.code,
            "message": item.message,
            "context": item.context,
        }
        for item in readiness.items
        if item.severity.value in {"hard_blocker", "warning"}
    )


def _provider_summary(steps: tuple[GuidedCloseStep, ...]) -> tuple[dict[str, object], ...]:
    provider_ids = {
        GuidedCloseStepId.ALFA_BASELINE,
        GuidedCloseStepId.MARKET_QUOTES,
        GuidedCloseStepId.ACTUAL_PAYOUTS,
        GuidedCloseStepId.FUTURE_PAYOUTS,
    }
    return tuple(
        {
            "step_id": step.id.value,
            "state": step.state.value,
            "evidence_scope": step.evidence_scope.value,
            "reason_codes": list(step.reason_codes),
            "evidence_summary": step.evidence_summary,
        }
        for step in steps
        if step.id in provider_ids
    )


def _evidence_version(
    month: object,
    readiness: CloseReadiness,
    freshness: FreshnessProvenanceSummary | None,
    cards: tuple[dict[str, object], ...],
    ladder: CashFlowLadderResult | None,
) -> str:
    material = [
        getattr(month, "id"),
        getattr(month, "status"),
        getattr(month, "snapshot_date"),
        getattr(month, "updated_at", None),
        [(item.severity.value, item.code, item.message) for item in readiness.items],
        [
            (card["id"], card["available"], card["reason_code"], repr(card["summary"]))
            for card in cards
        ],
    ]
    if freshness is not None:
        material.append(
            [
                (
                    family.family_id.value,
                    family.status.value,
                    tuple(reason.code.value for reason in family.reasons),
                )
                for family in freshness.families
            ]
        )
    if ladder is not None:
        material.append(
            [
                (event.expected_date, event.flow_type, event.expected_net_amount.kopecks)
                for month_bucket in ladder.months
                for event in month_bucket.items
            ]
        )
    return hashlib.sha256(repr(material).encode("utf-8")).hexdigest()


def build_final_month_review(
    session: Session,
    month: object,
    *,
    readiness: CloseReadiness,
    freshness: FreshnessProvenanceSummary | None,
    steps: tuple[GuidedCloseStep, ...],
) -> FinalMonthReview:
    """Compose the final review from existing read models only."""
    month_id = getattr(month, "id")
    if getattr(month, "snapshot_date") is None:
        summary = monthly_summary(session, month_id)
        dashboard = None
        ladder = None
    else:
        dashboard = build_dashboard(session, month_id)
        summary = dashboard.summary
        ladder = dashboard.cash_flow_ladder
    cards = _manual_review_cards(session, month, summary)
    return FinalMonthReview(
        summary=summary,
        dashboard=dashboard,
        cash_flow_ladder=ladder,
        readiness=readiness,
        freshness=freshness,
        provider_summary=_provider_summary(steps),
        reconciliation_availability={
            "available": False,
            "reason_code": GuidedCloseReasonCode.RECONCILIATION_NOT_RUN.value,
        },
        manual_review_cards=cards,
        manual_attention=_manual_attention(readiness),
        evidence_version=_evidence_version(month, readiness, freshness, cards, ladder),
    )


def build_next_month_outlook(session: Session, month: object) -> NextMonthOutlook:
    """Compose only dated, already-persisted facts after an explicit close."""
    if getattr(month, "status") != "closed":
        return NextMonthOutlook(
            available=False,
            reason_code=GuidedCloseReasonCode.OUTLOOK_NOT_AVAILABLE_UNTIL_CLOSED.value,
            source_month=month,
            cash_flow_ladder=None,
            next_month=None,
            known_event_count=0,
            evidence_version=None,
        )
    if getattr(month, "snapshot_date") is None:
        return NextMonthOutlook(
            available=False,
            reason_code=GuidedCloseReasonCode.OUTLOOK_SECTION_UNAVAILABLE.value,
            source_month=month,
            cash_flow_ladder=None,
            next_month=None,
            known_event_count=0,
            evidence_version=None,
        )
    ladder = build_cash_flow_ladder(session, getattr(month, "id"))
    next_year = getattr(month, "year") + (1 if getattr(month, "month") == 12 else 0)
    next_month_number = 1 if getattr(month, "month") == 12 else getattr(month, "month") + 1
    bucket = next(
        (
            item
            for item in ladder.months
            if (item.year, item.month) == (next_year, next_month_number)
        ),
        None,
    )
    if bucket is None:
        return NextMonthOutlook(
            available=False,
            reason_code=GuidedCloseReasonCode.OUTLOOK_SECTION_UNAVAILABLE.value,
            source_month=month,
            cash_flow_ladder=ladder,
            next_month=(next_year, next_month_number),
            known_event_count=0,
            evidence_version=None,
        )
    version = hashlib.sha256(
        repr(
            [
                getattr(month, "id"),
                (next_year, next_month_number),
                [
                    (event.expected_date, event.flow_type, event.expected_net_amount.kopecks)
                    for event in bucket.items
                ],
            ]
        ).encode("utf-8")
    ).hexdigest()
    return NextMonthOutlook(
        available=True,
        reason_code=None if bucket.items else GuidedCloseReasonCode.NO_KNOWN_DATED_EVENTS.value,
        source_month=month,
        cash_flow_ladder=ladder,
        next_month=(next_year, next_month_number),
        known_event_count=len(bucket.items),
        evidence_version=version,
    )


def _next_month_outlook_step(session: Session, month: object) -> GuidedCloseStep:
    outlook = build_next_month_outlook(session, month)
    if not outlook.available:
        return _step(
            step_id=GuidedCloseStepId.NEXT_MONTH_OUTLOOK,
            state=GuidedCloseStepState.WARNING,
            applicability=GuidedCloseApplicability.CONDITIONAL,
            gate=GuidedCloseGate.NONE,
            affects_close=False,
            why="После закрытия read-only outlook недоступен.",
            reason_codes=(
                outlook.reason_code or GuidedCloseReasonCode.OUTLOOK_SECTION_UNAVAILABLE.value,
            ),
            primary_action=_action(
                GuidedCloseActionId.OPEN_CASH_FLOW_LADDER, GuidedCloseActionTarget.INTERNAL_ROUTE
            ),
            evidence_summary=_unavailable_evidence(
                outlook.reason_code or GuidedCloseReasonCode.OUTLOOK_SECTION_UNAVAILABLE.value
            ),
        )
    bucket = next(
        item
        for item in outlook.cash_flow_ladder.months
        if outlook.next_month == (item.year, item.month)
    )
    return _step(
        step_id=GuidedCloseStepId.NEXT_MONTH_OUTLOOK,
        state=GuidedCloseStepState.COMPLETED,
        applicability=GuidedCloseApplicability.CONDITIONAL,
        gate=GuidedCloseGate.NONE,
        affects_close=False,
        why="Закрытый месяц показывает только уже известные датированные события следующего месяца.",
        reason_codes=(outlook.reason_code,) if outlook.reason_code else (),
        primary_action=_action(
            GuidedCloseActionId.OPEN_CASH_FLOW_LADDER, GuidedCloseActionTarget.INTERNAL_ROUTE
        ),
        secondary_actions=(
            _action(GuidedCloseActionId.CLONE_NEXT_MONTH, GuidedCloseActionTarget.INTERNAL_ROUTE),
        ),
        completion_basis=GuidedCloseCompletionBasis.BACKEND_READ,
        evidence_scope=GuidedCloseEvidenceScope.FULL_CURRENT_LOCAL_SCOPE,
        evidence_version=outlook.evidence_version,
        evidence_summary={
            "available": True,
            "known_event_count": outlook.known_event_count,
            "next_month": {"year": bucket.year, "month": bucket.month},
        },
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
                *(_closed_read_only_step(step_id) for step_id, _title in _STEP_DEFINITIONS[1:6]),
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
                _next_month_outlook_step(session, month),
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
                _alfa_baseline_step(session, month),
                (
                    _market_quote_step(freshness, session=session, month_id=month.id)
                    if freshness is not None
                    else _provider_step_read_only(
                        step_id=GuidedCloseStepId.MARKET_QUOTES,
                        why="Без даты снимка проверка котировок недоступна.",
                        reason_code="snapshot_date_required",
                        action_id=GuidedCloseActionId.OPEN_QUOTE_PREVIEW,
                    )
                ),
                _actual_payouts_step(session, month),
                _future_payouts_step(session, month),
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
        recommended = GuidedCloseStepId.NEXT_MONTH_OUTLOOK if closed else recommended_step_id(steps)
        return month, readiness, freshness, steps, recommended, clock
