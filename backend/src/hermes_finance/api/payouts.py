"""Owner-triggered payout preview/apply and merged calendar API (R05-08)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import (
    close_owned_payout_resource,
    resolve_payout_provider,
)
from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import MarketMappingState, RubleAmount
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import (
    PayoutFailure,
    PayoutFetchRequest,
    PayoutFetchResult,
    PayoutProvider,
)
from hermes_finance.persistence import AppliedProviderPayout, PositionSnapshot, ReportingMonth
from hermes_finance.services.applied_payouts import PayoutCountingDecision
from hermes_finance.services.instrument_mappings import get_instrument_mapping
from hermes_finance.services.payout_apply import (
    ManualDuplicateDecision,
    PayoutApplyResult,
    PayoutApplySelection,
    apply_payout_preview,
)
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.payout_preview import (
    PayoutMappingRequiredError,
    PayoutPreviewResult,
    build_payout_preview,
)
from hermes_finance.services.positions import PositionSnapshotNotFoundError
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError

router = APIRouter(tags=["payouts"])


class PayoutContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int = Field(gt=0)
    instrument_id: int = Field(gt=0)
    position_snapshot_id: int = Field(gt=0)
    forecast_version: str = Field(min_length=1, max_length=32)


class PayoutReconciliationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_id: int
    expected_cash_flow_id: int
    counting_decision: str


class PayoutPreviewRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    reporting_month_id: int
    account_id: int
    instrument_id: int
    position_snapshot_id: int | None
    quantity: str | None
    provider: str
    instrument_uid: str
    event_kind: str | None
    identity_key: str | None
    payment_date: date | None
    per_unit_amount: str | None
    currency: str | None
    total_amount: MoneyValue | None
    provider_status: str | None
    source_method: str | None
    applied_payout_id: int | None
    applied_lifecycle: str | None
    manual_candidate_ids: list[int]
    reconciliation: PayoutReconciliationOut | None
    selectable: bool
    default_selected: bool
    fingerprint: str | None
    message: str | None


class PayoutPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    account_id: int
    instrument_id: int
    position_snapshot_id: int | None
    quantity: str | None
    provider: str
    instrument_uid: str
    rows: list[PayoutPreviewRowOut]


class PayoutBatchPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_version: str = Field(min_length=1, max_length=32)
    position_snapshot_ids: list[int] | None = Field(default=None, max_length=500)


class PayoutBatchPreviewItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    instrument_id: int
    position_snapshot_id: int
    provider: str | None
    instrument_uid: str | None
    status: str
    message: str | None
    preview: PayoutPreviewResponse | None


class PayoutBatchPreviewSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_positions: int
    eligible_positions: int
    with_events: int
    without_events: int
    errors: int
    skipped: int


class PayoutBatchPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    forecast_version: str
    summary: PayoutBatchPreviewSummaryOut
    items: list[PayoutBatchPreviewItemOut]


class PayoutRefreshStatusItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    instrument_id: int
    position_snapshot_id: int
    current_quantity: str
    frozen_quantity: str
    applied_payout_count: int


class PayoutRefreshStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    positions_changed: int
    items: list[PayoutRefreshStatusItemOut]


class ManualDuplicateDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_cash_flow_id: int = Field(gt=0)
    counting_decision: str


class PayoutApplySelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32)
    instrument_uid: str = Field(min_length=1, max_length=128)
    event_kind: str = Field(min_length=1, max_length=16)
    identity_key: str = Field(min_length=1, max_length=128)
    fingerprint: str = Field(min_length=1, max_length=128)
    manual_duplicate_decision: ManualDuplicateDecisionIn | None = None


class PayoutApplyRequest(PayoutContextRequest):
    rows: list[PayoutApplySelectionIn] = Field(min_length=1)


class PayoutApplyItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payout_id: int
    revision_id: int
    revision_kind: str
    provider: str
    instrument_uid: str
    event_kind: str
    identity_key: str
    lifecycle: str
    total_amount: MoneyValue
    reconciliation_id: int | None
    counting_decision: str | None
    expected_cash_flow_id: int | None


class PayoutApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    selected_count: int
    items: list[PayoutApplyItemOut]
    error_code: str | None
    message: str | None


class PayoutCalendarItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str
    source_id: int
    expected_date: date
    flow_type: str
    account_id: int
    account_name: str
    instrument_id: int
    instrument_name: str | None
    expected_net_amount: MoneyValue
    is_confirmed: bool | None
    is_approximate: bool
    manual_source: str | None
    provider: str | None
    provider_instrument_uid: str | None
    provider_identity_key: str | None
    provider_lifecycle: str | None
    reconciliation_id: int | None
    counting_decision: str | None
    linked_manual_id: int | None
    linked_provider_payout_id: int | None


class PayoutCalendarMonthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    coupon: MoneyValue
    dividend: MoneyValue
    interest: MoneyValue
    redemption: MoneyValue
    other: MoneyValue
    passive_net: MoneyValue
    total_net: MoneyValue
    items: list[PayoutCalendarItemOut]


@dataclass(frozen=True, slots=True)
class _ResolvedPayoutContext:
    provider: str
    instrument_uid: str
    provider_request: PayoutFetchRequest


def _money(kopecks: int | None) -> MoneyValue | None:
    if kopecks is None:
        return None
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _money_amount(amount: RubleAmount) -> MoneyValue:
    return MoneyValue(amount=amount.to_api(), currency="RUB")


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, month=2, day=28)


def _resolve_context(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    position_snapshot_id: int,
) -> _ResolvedPayoutContext:
    with session.no_autoflush:
        month = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")

        snapshot = session.get(PositionSnapshot, position_snapshot_id)
        if snapshot is None:
            raise PositionSnapshotNotFoundError(
                f"position snapshot {position_snapshot_id} was not found"
            )
        if (
            snapshot.reporting_month_id != reporting_month_id
            or snapshot.account_id != account_id
            or snapshot.instrument_id != instrument_id
        ):
            raise ValueError(
                "position snapshot must match the requested reporting month, account and instrument"
            )

        mapping = get_instrument_mapping(session, instrument_id)
        if mapping.state is not MarketMappingState.MAPPED or mapping.identity is None:
            if mapping.state is MarketMappingState.EXCLUDED:
                raise PayoutMappingRequiredError(
                    "instrument is excluded from provider payout refresh"
                )
            raise PayoutMappingRequiredError("instrument has no accepted payout provider mapping")
        if mapping.identity.provider != T_INVEST_PROVIDER:
            raise PayoutMappingRequiredError("payout refresh requires an accepted t_invest mapping")

        start = month.snapshot_date
        end_exclusive = _one_year_after(start)
        request = PayoutFetchRequest(
            instrument_uid=mapping.identity.provider_instrument_id,
            calendar_from=start,
            calendar_to=end_exclusive - timedelta(days=1),
        )
        return _ResolvedPayoutContext(
            provider=T_INVEST_PROVIDER,
            instrument_uid=mapping.identity.provider_instrument_id,
            provider_request=request,
        )


def _safe_fetch(
    provider: PayoutProvider,
    context: _ResolvedPayoutContext,
) -> PayoutFetchResult:
    try:
        result = provider.fetch_payouts(context.provider_request)
    except Exception:
        result = None
    if (
        not isinstance(result, PayoutFetchResult)
        or result.provider != context.provider
        or result.instrument_uid != context.instrument_uid
    ):
        return PayoutFetchResult(
            provider=context.provider,
            instrument_uid=context.instrument_uid,
            failures=(
                PayoutFailure(
                    status=PayoutEventStatus.ERROR,
                    message="Payout provider refresh failed",
                ),
            ),
        )
    return result


def _preview_response(result: PayoutPreviewResult) -> PayoutPreviewResponse:
    return PayoutPreviewResponse(
        reporting_month_id=result.reporting_month_id,
        account_id=result.account_id,
        instrument_id=result.instrument_id,
        position_snapshot_id=result.position_snapshot_id,
        quantity=_decimal_text(result.quantity),
        provider=result.provider,
        instrument_uid=result.instrument_uid,
        rows=[
            PayoutPreviewRowOut(
                status=row.status.value,
                reporting_month_id=row.reporting_month_id,
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                position_snapshot_id=row.position_snapshot_id,
                quantity=_decimal_text(row.quantity),
                provider=row.provider,
                instrument_uid=row.instrument_uid,
                event_kind=row.event_kind.value if row.event_kind is not None else None,
                identity_key=row.identity_key,
                payment_date=row.payment_date,
                per_unit_amount=_decimal_text(row.per_unit_amount),
                currency=row.currency,
                total_amount=_money(row.total_amount_kopecks),
                provider_status=row.provider_status,
                source_method=row.source_method,
                applied_payout_id=row.applied_payout_id,
                applied_lifecycle=row.applied_lifecycle,
                manual_candidate_ids=list(row.manual_candidate_ids),
                reconciliation=(
                    PayoutReconciliationOut(
                        reconciliation_id=row.reconciliation.reconciliation_id,
                        expected_cash_flow_id=row.reconciliation.expected_cash_flow_id,
                        counting_decision=row.reconciliation.counting_decision,
                    )
                    if row.reconciliation is not None
                    else None
                ),
                selectable=row.selectable,
                default_selected=row.default_selected,
                fingerprint=row.fingerprint,
                message=row.message,
            )
            for row in result.rows
        ],
    )


def _batch_item_status(preview: PayoutPreviewResult) -> tuple[str, bool, bool, bool]:
    event_rows = [row for row in preview.rows if row.event_kind is not None]
    has_error = any(row.status.value == PayoutEventStatus.ERROR.value for row in preview.rows)
    if has_error:
        return "error", bool(event_rows), False, True
    if not event_rows:
        return "no_events", False, True, False
    return "previewed", True, False, False


def _refresh_status(
    session: Session,
    *,
    reporting_month_id: int,
) -> PayoutRefreshStatusResponse:
    month = session.get(ReportingMonth, reporting_month_id)
    if month is None:
        raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")

    snapshots = list(
        session.scalars(
            select(PositionSnapshot)
            .where(PositionSnapshot.reporting_month_id == reporting_month_id)
            .order_by(
                PositionSnapshot.account_id, PositionSnapshot.instrument_id, PositionSnapshot.id
            )
        )
    )
    payouts = list(
        session.scalars(
            select(AppliedProviderPayout)
            .where(
                AppliedProviderPayout.reporting_month_id == reporting_month_id,
                AppliedProviderPayout.provider == T_INVEST_PROVIDER,
                AppliedProviderPayout.lifecycle == "active",
            )
            .order_by(AppliedProviderPayout.id)
        )
    )
    by_position = {}
    for payout in payouts:
        by_position.setdefault((payout.account_id, payout.instrument_id), []).append(payout)

    items: list[PayoutRefreshStatusItemOut] = []
    for snapshot in snapshots:
        related = by_position.get((snapshot.account_id, snapshot.instrument_id), [])
        stale = [
            payout
            for payout in related
            if payout.source_position_snapshot_id != snapshot.id
            or payout.quantity != snapshot.quantity
        ]
        if not stale:
            continue
        items.append(
            PayoutRefreshStatusItemOut(
                account_id=snapshot.account_id,
                instrument_id=snapshot.instrument_id,
                position_snapshot_id=snapshot.id,
                current_quantity=_decimal_text(snapshot.quantity) or "0",
                frozen_quantity=_decimal_text(stale[0].quantity) or "0",
                applied_payout_count=len(stale),
            )
        )
    return PayoutRefreshStatusResponse(
        reporting_month_id=month.id,
        positions_changed=len(items),
        items=items,
    )


def _apply_selection(
    row: PayoutApplySelectionIn,
    *,
    context: _ResolvedPayoutContext,
) -> PayoutApplySelection:
    provider = row.provider.strip()
    instrument_uid = row.instrument_uid.strip()
    if provider != context.provider or instrument_uid != context.instrument_uid:
        raise ValueError("selected payout identity does not match the accepted local mapping")

    duplicate = None
    if row.manual_duplicate_decision is not None:
        duplicate = ManualDuplicateDecision(
            counting_decision=PayoutCountingDecision(
                row.manual_duplicate_decision.counting_decision
            ),
            expected_cash_flow_id=row.manual_duplicate_decision.expected_cash_flow_id,
        )
    return PayoutApplySelection(
        provider=context.provider,
        instrument_uid=context.instrument_uid,
        event_kind=PayoutEventKind(row.event_kind),
        identity_key=row.identity_key,
        fingerprint=row.fingerprint,
        manual_duplicate_decision=duplicate,
    )


def _apply_response(result: PayoutApplyResult) -> PayoutApplyResponse:
    return PayoutApplyResponse(
        success=result.success,
        selected_count=result.selected_count,
        items=[
            PayoutApplyItemOut(
                payout_id=item.payout_id,
                revision_id=item.revision_id,
                revision_kind=item.revision_kind,
                provider=item.provider,
                instrument_uid=item.instrument_uid,
                event_kind=item.event_kind.value,
                identity_key=item.identity_key,
                lifecycle=item.lifecycle,
                total_amount=_money(item.total_amount_kopecks),  # type: ignore[arg-type]
                reconciliation_id=item.reconciliation_id,
                counting_decision=item.counting_decision,
                expected_cash_flow_id=item.expected_cash_flow_id,
            )
            for item in result.items
        ],
        error_code=result.error_code.value if result.error_code is not None else None,
        message=result.message,
    )


@router.post("/api/months/{month_id}/payout-preview", response_model=PayoutPreviewResponse)
def payout_preview_endpoint(
    month_id: int,
    payload: PayoutContextRequest,
    request: Request,
    session: Session = Depends(session_for_request),
) -> PayoutPreviewResponse:
    context = _resolve_context(
        session,
        reporting_month_id=month_id,
        account_id=payload.account_id,
        instrument_id=payload.instrument_id,
        position_snapshot_id=payload.position_snapshot_id,
    )
    provider, owned_resource = resolve_payout_provider(request)
    try:
        fetch_result = _safe_fetch(provider, context)
        result = build_payout_preview(
            session,
            reporting_month_id=month_id,
            account_id=payload.account_id,
            instrument_id=payload.instrument_id,
            position_snapshot_id=payload.position_snapshot_id,
            forecast_version=payload.forecast_version,
            fetch_result=fetch_result,
        )
    finally:
        close_owned_payout_resource(owned_resource)
    return _preview_response(result)


@router.post(
    "/api/months/{month_id}/payout-batch-preview",
    response_model=PayoutBatchPreviewResponse,
)
def payout_batch_preview_endpoint(
    month_id: int,
    payload: PayoutBatchPreviewRequest,
    request: Request,
    session: Session = Depends(session_for_request),
) -> PayoutBatchPreviewResponse:
    month = session.get(ReportingMonth, month_id)
    if month is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")

    snapshot_query = select(PositionSnapshot).where(PositionSnapshot.reporting_month_id == month_id)
    if payload.position_snapshot_ids is not None:
        snapshot_query = snapshot_query.where(
            PositionSnapshot.id.in_(payload.position_snapshot_ids)
        )
    snapshots = list(
        session.scalars(
            snapshot_query.order_by(
                PositionSnapshot.account_id,
                PositionSnapshot.instrument_id,
                PositionSnapshot.id,
            )
        )
    )
    items: list[PayoutBatchPreviewItemOut] = []
    eligible = with_events = without_events = errors = skipped = 0
    provider, owned_resource = resolve_payout_provider(request)
    try:
        for snapshot in snapshots:
            mapping = get_instrument_mapping(session, snapshot.instrument_id)
            if mapping.state is not MarketMappingState.MAPPED or mapping.identity is None:
                skipped += 1
                message = (
                    "Позиция исключена из обновления"
                    if mapping.state is MarketMappingState.EXCLUDED
                    else "Нет принятого сопоставления T-Invest"
                )
                items.append(
                    PayoutBatchPreviewItemOut(
                        account_id=snapshot.account_id,
                        instrument_id=snapshot.instrument_id,
                        position_snapshot_id=snapshot.id,
                        provider=None,
                        instrument_uid=None,
                        status="skipped",
                        message=message,
                        preview=None,
                    )
                )
                continue
            if mapping.identity.provider != T_INVEST_PROVIDER:
                skipped += 1
                items.append(
                    PayoutBatchPreviewItemOut(
                        account_id=snapshot.account_id,
                        instrument_id=snapshot.instrument_id,
                        position_snapshot_id=snapshot.id,
                        provider=mapping.identity.provider,
                        instrument_uid=mapping.identity.provider_instrument_id,
                        status="skipped",
                        message="Принятое сопоставление не поддерживает payout refresh T-Invest",
                        preview=None,
                    )
                )
                continue

            eligible += 1
            try:
                context = _resolve_context(
                    session,
                    reporting_month_id=month_id,
                    account_id=snapshot.account_id,
                    instrument_id=snapshot.instrument_id,
                    position_snapshot_id=snapshot.id,
                )
                fetch_result = _safe_fetch(provider, context)
                result = build_payout_preview(
                    session,
                    reporting_month_id=month_id,
                    account_id=snapshot.account_id,
                    instrument_id=snapshot.instrument_id,
                    position_snapshot_id=snapshot.id,
                    forecast_version=payload.forecast_version,
                    fetch_result=fetch_result,
                )
                status, has_events, no_events, has_error = _batch_item_status(result)
                with_events += int(has_events)
                without_events += int(no_events)
                errors += int(has_error)
                items.append(
                    PayoutBatchPreviewItemOut(
                        account_id=snapshot.account_id,
                        instrument_id=snapshot.instrument_id,
                        position_snapshot_id=snapshot.id,
                        provider=result.provider,
                        instrument_uid=result.instrument_uid,
                        status=status,
                        message=None,
                        preview=_preview_response(result),
                    )
                )
            except Exception:
                errors += 1
                items.append(
                    PayoutBatchPreviewItemOut(
                        account_id=snapshot.account_id,
                        instrument_id=snapshot.instrument_id,
                        position_snapshot_id=snapshot.id,
                        provider=T_INVEST_PROVIDER,
                        instrument_uid=mapping.identity.provider_instrument_id,
                        status="error",
                        message="Не удалось подготовить preview позиции",
                        preview=None,
                    )
                )
    finally:
        close_owned_payout_resource(owned_resource)

    return PayoutBatchPreviewResponse(
        reporting_month_id=month_id,
        forecast_version=payload.forecast_version.strip(),
        summary=PayoutBatchPreviewSummaryOut(
            total_positions=len(snapshots),
            eligible_positions=eligible,
            with_events=with_events,
            without_events=without_events,
            errors=errors,
            skipped=skipped,
        ),
        items=items,
    )


@router.get(
    "/api/months/{month_id}/payout-refresh-status",
    response_model=PayoutRefreshStatusResponse,
)
def payout_refresh_status_endpoint(
    month_id: int,
    session: Session = Depends(session_for_request),
) -> PayoutRefreshStatusResponse:
    return _refresh_status(session, reporting_month_id=month_id)


@router.post("/api/months/{month_id}/payout-apply", response_model=PayoutApplyResponse)
def payout_apply_endpoint(
    month_id: int,
    payload: PayoutApplyRequest,
    request: Request,
    session: Session = Depends(session_for_request),
) -> PayoutApplyResponse:
    context = _resolve_context(
        session,
        reporting_month_id=month_id,
        account_id=payload.account_id,
        instrument_id=payload.instrument_id,
        position_snapshot_id=payload.position_snapshot_id,
    )
    selections = tuple(_apply_selection(row, context=context) for row in payload.rows)
    provider, owned_resource = resolve_payout_provider(request)
    try:
        result = apply_payout_preview(
            session,
            provider=provider,
            provider_request=context.provider_request,
            reporting_month_id=month_id,
            account_id=payload.account_id,
            instrument_id=payload.instrument_id,
            position_snapshot_id=payload.position_snapshot_id,
            forecast_version=payload.forecast_version,
            selections=selections,
        )
    finally:
        close_owned_payout_resource(owned_resource)
    return _apply_response(result)


@router.get("/api/payouts/calendar", response_model=list[PayoutCalendarMonthOut])
def payout_calendar_endpoint(
    month_id: int = Query(...),
    forecast_version: str = Query(...),
    from_date: date | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[PayoutCalendarMonthOut]:
    months = merged_payout_calendar(
        session,
        reporting_month_id=month_id,
        forecast_version=forecast_version,
        from_date=from_date,
    )
    return [
        PayoutCalendarMonthOut(
            year=month.year,
            month=month.month,
            coupon=_money_amount(month.coupon),
            dividend=_money_amount(month.dividend),
            interest=_money_amount(month.interest),
            redemption=_money_amount(month.redemption),
            other=_money_amount(month.other),
            passive_net=_money_amount(month.passive_net),
            total_net=_money_amount(month.total_net),
            items=[
                PayoutCalendarItemOut(
                    source_kind=item.source_kind.value,
                    source_id=item.source_id,
                    expected_date=item.expected_date,
                    flow_type=item.flow_type,
                    account_id=item.account_id,
                    account_name=item.account_name,
                    instrument_id=item.instrument_id,
                    instrument_name=item.instrument_name,
                    expected_net_amount=_money_amount(item.expected_net_amount),
                    is_confirmed=item.is_confirmed,
                    is_approximate=item.is_approximate,
                    manual_source=item.manual_source,
                    provider=item.provider,
                    provider_instrument_uid=item.provider_instrument_uid,
                    provider_identity_key=item.provider_identity_key,
                    provider_lifecycle=item.provider_lifecycle,
                    reconciliation_id=item.reconciliation_id,
                    counting_decision=item.counting_decision,
                    linked_manual_id=item.linked_manual_id,
                    linked_provider_payout_id=item.linked_provider_payout_id,
                )
                for item in month.items
            ],
        )
        for month in months
    ]
