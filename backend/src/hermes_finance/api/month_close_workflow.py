"""Versioned HTTP boundary for the provider-free monthly close workflow."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.cash_flow_ladder import (
    CashFlowLadderEventOut,
    UpcomingEventsWindowOut,
    cash_flow_ladder_to_out,
)
from hermes_finance.api.close_readiness import (
    CloseReadinessOut,
    _latest_backup,
)
from hermes_finance.api.close_readiness import (
    _readiness_out as _close_readiness_out,
)
from hermes_finance.api.dashboard import (
    InstrumentClassResultOut,
    KpiOut,
    LiquidCapitalOut,
    _liquid_out,
    dashboard_to_out,
)
from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import MoneyValue, _database_for_request, session_for_request
from hermes_finance.database import Database
from hermes_finance.domain.month_close_workflow import (
    GuidedCloseAction,
    GuidedCloseStep,
    GuidedCloseStepId,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.cash import total_cash
from hermes_finance.services.close_readiness import CloseReadiness
from hermes_finance.services.debts import total_debts
from hermes_finance.services.freshness_provenance import FreshnessProvenanceSummary
from hermes_finance.services.month_close_workflow import (
    WORKFLOW_CONTRACT_VERSION,
    FinalMonthReview,
    NextMonthOutlook,
    build_final_month_review,
    build_month_close_workflow,
    build_next_month_outlook,
)
from hermes_finance.services.properties import (
    mortgage_coverage,
    total_mortgage_balance,
    total_property_value,
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


class ManualReviewCardOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    available: bool
    reason_code: str | None
    summary: dict[str, object]


class ManualAttentionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str
    severity: str
    code: str
    message: str
    context: dict[str, object]


class FinalAssetsAndCashOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason_code: str | None
    liquid_capital: LiquidCapitalOut | None
    current_cash: MoneyValue | None
    cash_row_count: int


class FinalDebtsAndPropertyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason_code: str | None
    debt_total: MoneyValue | None
    property_value: MoneyValue | None
    mortgage_balance: MoneyValue | None
    debt_row_count: int
    property_row_count: int


class FinalInvestmentsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason_code: str | None
    position_count: int
    market_value: MoneyValue | None
    manual_price_count: int
    actual_flow_count: int
    future_flow_count: int
    by_instrument_class: list[InstrumentClassResultOut]


class NextMonthBucketOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    known_event_count: int
    has_known_events: bool
    passive_income: MoneyValue | None
    redemption_principal: MoneyValue | None
    total_cash_flow: MoneyValue | None
    deposit_interest_estimate: MoneyValue | None
    items: list[CashFlowLadderEventOut]


class ImportantFutureEventsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason_code: str | None
    upcoming_14_days: UpcomingEventsWindowOut | None
    upcoming_30_days: UpcomingEventsWindowOut | None
    next_month: NextMonthBucketOut | None
    known_event_count: int


class FinalMonthReviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason_code: str | None
    month_header: WorkflowMonthOut
    kpis: KpiOut
    assets_and_cash: FinalAssetsAndCashOut
    debts_and_property: FinalDebtsAndPropertyOut
    investments: FinalInvestmentsOut
    actual_passive_income: MoneyValue
    important_future_events: ImportantFutureEventsOut
    provider_summary: list[dict[str, object]]
    reconciliation_availability: dict[str, object]
    freshness_summary: WorkflowFreshnessOut
    close_readiness: CloseReadinessOut
    manual_review_cards: list[ManualReviewCardOut]
    manual_attention: list[ManualAttentionOut]
    evidence_version: str


class NextMonthOutlookOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason_code: str | None
    source_month: WorkflowMonthOut
    next_month: NextMonthBucketOut | None
    upcoming_14_days: UpcomingEventsWindowOut | None
    upcoming_30_days: UpcomingEventsWindowOut | None
    known_event_count: int
    evidence_version: str | None


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
    final_review: FinalMonthReviewOut
    outlook: NextMonthOutlookOut | None
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


def _money(amount: RubleAmount | None) -> MoneyValue | None:
    return None if amount is None else MoneyValue(amount=amount.to_api(), currency="RUB")


def _workflow_month_out(month: object) -> WorkflowMonthOut:
    return WorkflowMonthOut(
        id=month.id,
        year=month.year,
        month=month.month,
        status=month.status,
        snapshot_date=month.snapshot_date,
        source=month.source,
    )


def _value_out(value: object) -> object:
    if isinstance(value, RubleAmount):
        return MoneyValue(amount=value.to_api(), currency="RUB")
    if isinstance(value, dict):
        return {key: _value_out(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value_out(item) for item in value]
    return value


def _kpis_out(
    session: Session, review: FinalMonthReview, month: object
) -> tuple[KpiOut, list[InstrumentClassResultOut]]:
    if review.dashboard is not None:
        dashboard_out = dashboard_to_out(review.dashboard)
        return dashboard_out.kpis, dashboard_out.result_by_instrument_class

    summary = review.summary
    mortgage_balance = total_mortgage_balance(session, month.id)
    coverage_pct, _gap = mortgage_coverage(
        session, month.id, summary.liquid_capital.liquid_capital_net
    )
    return (
        KpiOut(
            liquid_capital_net=MoneyValue(
                amount=summary.liquid_capital.liquid_capital_net.to_api(), currency="RUB"
            ),
            liquid_capital_delta=_money(summary.liquid_capital_delta),
            passive_income_actual=MoneyValue(
                amount=summary.passive_income_actual.to_api(), currency="RUB"
            ),
            passive_income_delta=_money(summary.passive_income_delta),
            forecast_monthly_passive_income=MoneyValue(
                amount=summary.forecast.monthly_total.to_api(), currency="RUB"
            ),
            forecast_annual_passive_income=MoneyValue(
                amount=summary.forecast.annual_total.to_api(), currency="RUB"
            ),
            passive_income_average=MoneyValue(
                amount=summary.passive_income_average.to_api(), currency="RUB"
            ),
            passive_income_average_months=summary.passive_income_average_months,
            passive_income_average_complete=summary.passive_income_average_complete,
            passive_income_history_start_month=summary.passive_income_history_start_month,
            passive_income_average_months_used=list(summary.passive_income_average_months_used),
            goal_progress_pct=(
                format(summary.coverage.goal_progress_pct, "f")
                if summary.coverage.goal_progress_pct is not None
                else None
            ),
            goal_target=MoneyValue(amount=summary.coverage.goal_target.to_api(), currency="RUB"),
            mandatory_expenses=MoneyValue(
                amount=summary.coverage.mandatory_expenses.to_api(), currency="RUB"
            ),
            mandatory_expense_coverage_pct=(
                format(summary.coverage.coverage_pct, "f")
                if summary.coverage.coverage_pct is not None
                else None
            ),
            actual_mandatory_expense_coverage_pct=(
                format(summary.coverage.actual_mandatory_expense_coverage_pct, "f")
                if summary.coverage.actual_mandatory_expense_coverage_pct is not None
                else None
            ),
            mortgage_balance=MoneyValue(amount=mortgage_balance.to_api(), currency="RUB"),
            mortgage_coverage_pct=(format(coverage_pct, "f") if coverage_pct is not None else None),
        ),
        [],
    )


def _important_future_events_out(ladder: object | None) -> ImportantFutureEventsOut:
    if ladder is None:
        return ImportantFutureEventsOut(
            available=False,
            reason_code="snapshot_date_required",
            upcoming_14_days=None,
            upcoming_30_days=None,
            next_month=None,
            known_event_count=0,
        )
    ladder_out = cash_flow_ladder_to_out(ladder)
    source_year, source_month = ladder.months[0].year, ladder.months[0].month
    next_year = source_year + (1 if source_month == 12 else 0)
    next_month_number = 1 if source_month == 12 else source_month + 1
    bucket = next(
        (
            item
            for item in ladder_out.months
            if (item.year, item.month) == (next_year, next_month_number)
        ),
        None,
    )
    if bucket is None:
        return ImportantFutureEventsOut(
            available=False,
            reason_code="outlook_section_unavailable",
            upcoming_14_days=ladder_out.upcoming_14_days,
            upcoming_30_days=ladder_out.upcoming_30_days,
            next_month=None,
            known_event_count=0,
        )
    known = bool(bucket.items)
    return ImportantFutureEventsOut(
        available=True,
        reason_code=None if known else "no_known_dated_events",
        upcoming_14_days=ladder_out.upcoming_14_days,
        upcoming_30_days=ladder_out.upcoming_30_days,
        next_month=NextMonthBucketOut(
            year=bucket.year,
            month=bucket.month,
            known_event_count=len(bucket.items),
            has_known_events=known,
            passive_income=(bucket.passive_income if known else None),
            redemption_principal=(bucket.redemption_principal if known else None),
            total_cash_flow=(bucket.total_cash_flow if known else None),
            deposit_interest_estimate=(
                bucket.deposit_interest if bucket.deposit_interest.amount != "0.00" else None
            ),
            items=bucket.items,
        ),
        known_event_count=len(bucket.items),
    )


def _final_review_out(
    session: Session, review: FinalMonthReview, month: object
) -> FinalMonthReviewOut:
    kpis, instrument_classes = _kpis_out(session, review, month)
    summary = review.summary
    cards = [
        ManualReviewCardOut(
            id=card["id"],
            title=card["title"],
            available=card["available"],
            reason_code=card["reason_code"],
            summary=_value_out(card["summary"]),
        )
        for card in review.manual_review_cards
    ]
    liquid = _liquid_out(summary.liquid_capital)
    return FinalMonthReviewOut(
        available=True,
        reason_code=None,
        month_header=_workflow_month_out(month),
        kpis=kpis,
        assets_and_cash=FinalAssetsAndCashOut(
            available=True,
            reason_code=None,
            liquid_capital=liquid,
            current_cash=_money(total_cash(session, month.id)),
            cash_row_count=next(
                card["summary"]["row_count"]
                for card in review.manual_review_cards
                if card["id"] == "cash"
            ),
        ),
        debts_and_property=FinalDebtsAndPropertyOut(
            available=True,
            reason_code=None,
            debt_total=_money(total_debts(session, month.id)),
            property_value=_money(total_property_value(session, month.id)),
            mortgage_balance=_money(total_mortgage_balance(session, month.id)),
            debt_row_count=next(
                card["summary"]["debt_row_count"]
                for card in review.manual_review_cards
                if card["id"] == "debts_property"
            ),
            property_row_count=next(
                card["summary"]["property_row_count"]
                for card in review.manual_review_cards
                if card["id"] == "debts_property"
            ),
        ),
        investments=FinalInvestmentsOut(
            available=next(
                card["available"]
                for card in review.manual_review_cards
                if card["id"] == "investments_outside_integrations"
            ),
            reason_code=next(
                card["reason_code"]
                for card in review.manual_review_cards
                if card["id"] == "investments_outside_integrations"
            ),
            position_count=next(
                card["summary"]["position_count"]
                for card in review.manual_review_cards
                if card["id"] == "investments_outside_integrations"
            ),
            market_value=_money(summary.liquid_capital.breakdown.securities),
            manual_price_count=next(
                card["summary"]["manual_price_count"]
                for card in review.manual_review_cards
                if card["id"] == "investments_outside_integrations"
            ),
            actual_flow_count=next(
                card["summary"]["actual_flow_count"]
                for card in review.manual_review_cards
                if card["id"] == "investments_outside_integrations"
            ),
            future_flow_count=next(
                card["summary"]["future_flow_count"]
                for card in review.manual_review_cards
                if card["id"] == "investments_outside_integrations"
            ),
            by_instrument_class=instrument_classes,
        ),
        actual_passive_income=MoneyValue(
            amount=summary.passive_income_actual.to_api(), currency="RUB"
        ),
        important_future_events=_important_future_events_out(review.cash_flow_ladder),
        provider_summary=[_value_out(item) for item in review.provider_summary],
        reconciliation_availability=_value_out(review.reconciliation_availability),
        freshness_summary=_freshness_out(review.freshness),
        close_readiness=_close_readiness_out(review.readiness),
        manual_review_cards=cards,
        manual_attention=[
            ManualAttentionOut(**_value_out(item)) for item in review.manual_attention
        ],
        evidence_version=review.evidence_version,
    )


def _outlook_out(outlook: NextMonthOutlook) -> NextMonthOutlookOut:
    ladder_out = (
        cash_flow_ladder_to_out(outlook.cash_flow_ladder)
        if outlook.cash_flow_ladder is not None
        else None
    )
    bucket = None
    if outlook.next_month is not None and ladder_out is not None:
        candidate = next(
            (item for item in ladder_out.months if (item.year, item.month) == outlook.next_month),
            None,
        )
        if candidate is not None:
            known = bool(candidate.items)
            bucket = NextMonthBucketOut(
                year=candidate.year,
                month=candidate.month,
                known_event_count=len(candidate.items),
                has_known_events=known,
                passive_income=candidate.passive_income if known else None,
                redemption_principal=candidate.redemption_principal if known else None,
                total_cash_flow=candidate.total_cash_flow if known else None,
                deposit_interest_estimate=(
                    candidate.deposit_interest
                    if candidate.deposit_interest.amount != "0.00"
                    else None
                ),
                items=candidate.items,
            )
    return NextMonthOutlookOut(
        available=outlook.available,
        reason_code=outlook.reason_code,
        source_month=_workflow_month_out(outlook.source_month),
        next_month=bucket,
        upcoming_14_days=(ladder_out.upcoming_14_days if ladder_out is not None else None),
        upcoming_30_days=(ladder_out.upcoming_30_days if ladder_out is not None else None),
        known_event_count=outlook.known_event_count,
        evidence_version=outlook.evidence_version,
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
    final_review = build_final_month_review(
        session,
        month,
        readiness=readiness,
        freshness=freshness,
        steps=steps,
    )
    outlook = build_next_month_outlook(session, month) if month.status == "closed" else None
    completed_or_skipped = sum(
        step.state.value in {"completed", "skipped"}
        for step in steps
        if step.applicability.value != "not_applicable"
    )
    total_applicable = sum(step.applicability.value != "not_applicable" for step in steps)
    return GuidedCloseWorkflowOut(
        contract_version=WORKFLOW_CONTRACT_VERSION,
        generated_at=generated,
        month=_workflow_month_out(month),
        recommended_step_id=(
            recommended.value if isinstance(recommended, GuidedCloseStepId) else None
        ),
        progress=WorkflowProgressOut(
            completed_or_skipped=completed_or_skipped, total_applicable=total_applicable
        ),
        steps=[_step_out(step) for step in steps],
        readiness=_readiness_out(readiness),
        freshness=_freshness_out(freshness),
        final_review=_final_review_out(session, final_review, month),
        outlook=_outlook_out(outlook) if outlook is not None else None,
        links=WorkflowLinksOut(
            month=f"/months/{month.id}",
            close_readiness=f"/api/months/{month.id}/close-readiness",
            freshness=f"/api/months/{month.id}/freshness-provenance",
        ),
    )
