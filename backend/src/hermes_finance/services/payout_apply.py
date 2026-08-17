"""Transactional selective payout apply orchestration for R05-06."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from hermes_finance.market_data.payout import PayoutEventKind
from hermes_finance.market_data.payout_protocol import (
    PayoutFetchRequest,
    PayoutProvider,
)
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.applied_payouts import (
    AppliedPayoutLifecycle,
    AppliedPayoutRevisionKind,
    PayoutCountingDecision,
    append_applied_payout_revision,
    create_applied_payout,
    get_applied_payout,
    list_applied_payout_revisions,
    set_applied_payout_reconciliation,
)
from hermes_finance.services.payout_preview import (
    PayoutPreviewError,
    PayoutPreviewRow,
    PayoutPreviewStatus,
    build_payout_preview,
)
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    ReportingMonthNotFoundError,
)


class PayoutApplyFailureCode(StrEnum):
    PREVIEW_CHANGED = "preview_changed"
    VALIDATION_ERROR = "validation_error"
    PROVIDER_ERROR = "provider_error"
    PERSISTENCE_ERROR = "persistence_error"
    CLOSED_MONTH = "closed_month"


@dataclass(frozen=True, slots=True)
class ManualDuplicateDecision:
    counting_decision: PayoutCountingDecision
    expected_cash_flow_id: int

    def __post_init__(self) -> None:
        try:
            decision = PayoutCountingDecision(self.counting_decision)
        except (TypeError, ValueError) as error:
            raise ValueError("unsupported manual duplicate counting decision") from error
        object.__setattr__(self, "counting_decision", decision)
        if (
            isinstance(self.expected_cash_flow_id, bool)
            or not isinstance(self.expected_cash_flow_id, int)
            or self.expected_cash_flow_id <= 0
        ):
            raise ValueError("expected_cash_flow_id must be a positive integer")


@dataclass(frozen=True, slots=True)
class PayoutApplySelection:
    provider: str
    instrument_uid: str
    event_kind: PayoutEventKind
    identity_key: str
    fingerprint: str
    manual_duplicate_decision: ManualDuplicateDecision | None = None

    def __post_init__(self) -> None:
        try:
            kind = PayoutEventKind(self.event_kind)
        except (TypeError, ValueError) as error:
            raise ValueError("unsupported payout event kind") from error
        object.__setattr__(self, "event_kind", kind)
        for field_name in ("provider", "instrument_uid", "identity_key", "fingerprint"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True, slots=True)
class PayoutApplyItemResult:
    payout_id: int
    revision_id: int
    revision_kind: str
    provider: str
    instrument_uid: str
    event_kind: PayoutEventKind
    identity_key: str
    lifecycle: str
    total_amount_kopecks: int
    reconciliation_id: int | None = None
    counting_decision: str | None = None
    expected_cash_flow_id: int | None = None


@dataclass(frozen=True, slots=True)
class PayoutApplyResult:
    success: bool
    selected_count: int
    items: tuple[PayoutApplyItemResult, ...] = ()
    error_code: PayoutApplyFailureCode | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class _ApplyPlan:
    row: PayoutPreviewRow
    duplicate_decision: ManualDuplicateDecision | None


_APPLYABLE = {
    PayoutPreviewStatus.NEW,
    PayoutPreviewStatus.REVISED,
    PayoutPreviewStatus.POSSIBLE_MANUAL_DUPLICATE,
}


def apply_payout_preview(
    session: Session,
    *,
    provider: PayoutProvider,
    provider_request: PayoutFetchRequest,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    position_snapshot_id: int,
    forecast_version: str,
    selections: tuple[PayoutApplySelection, ...],
    fetched_at: datetime | None = None,
    applied_at: datetime | None = None,
) -> PayoutApplyResult:
    """Re-fetch, re-preview and atomically apply an explicit selected set."""

    selected_count = len(selections)
    if not selections:
        return _failure(
            selected_count,
            PayoutApplyFailureCode.VALIDATION_ERROR,
            "at least one payout row must be selected",
        )
    if not forecast_version.strip():
        return _failure(
            selected_count,
            PayoutApplyFailureCode.VALIDATION_ERROR,
            "forecast_version must not be empty",
        )
    if session.new or session.dirty or session.deleted:
        return _failure(
            selected_count,
            PayoutApplyFailureCode.VALIDATION_ERROR,
            "payout apply requires a clean database session",
        )
    if _has_duplicate_selections(selections):
        return _failure(
            selected_count,
            PayoutApplyFailureCode.VALIDATION_ERROR,
            "selected payout identities must be unique",
        )

    try:
        with session.no_autoflush:
            require_editable_reporting_month(session, reporting_month_id)
    except ClosedReportingMonthError:
        return _failure(
            selected_count,
            PayoutApplyFailureCode.CLOSED_MONTH,
            "closed reporting month must be reopened before payout apply",
        )
    except ReportingMonthNotFoundError:
        return _failure(
            selected_count,
            PayoutApplyFailureCode.VALIDATION_ERROR,
            "reporting month was not found",
        )

    try:
        fetch_result = provider.fetch_payouts(provider_request)
    except Exception:
        return _failure(
            selected_count,
            PayoutApplyFailureCode.PROVIDER_ERROR,
            "payout provider refresh failed",
        )

    if fetch_result.failures:
        failure = fetch_result.failures[0]
        return _failure(
            selected_count,
            PayoutApplyFailureCode.PROVIDER_ERROR,
            failure.message,
        )

    try:
        fresh_preview = build_payout_preview(
            session,
            reporting_month_id=reporting_month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            position_snapshot_id=position_snapshot_id,
            forecast_version=forecast_version,
            fetch_result=fetch_result,
        )
    except PayoutPreviewError:
        return _preview_changed(selected_count)

    plan_result = _build_apply_plan(selections, fresh_preview.rows)
    if isinstance(plan_result, PayoutApplyResult):
        return plan_result
    plans = plan_result

    fetched_timestamp = _timestamp(fetched_at)
    applied_timestamp = _timestamp(applied_at)
    item_results: list[PayoutApplyItemResult] = []

    try:
        for plan in plans:
            row = plan.row
            assert row.event_kind is not None
            assert row.identity_key is not None
            assert row.payment_date is not None
            assert row.per_unit_amount is not None
            assert row.currency is not None
            assert row.position_snapshot_id is not None

            if row.status in {
                PayoutPreviewStatus.NEW,
                PayoutPreviewStatus.POSSIBLE_MANUAL_DUPLICATE,
            }:
                payout = create_applied_payout(
                    session,
                    reporting_month_id=reporting_month_id,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    source_position_snapshot_id=row.position_snapshot_id,
                    provider=row.provider,
                    provider_instrument_uid=row.instrument_uid,
                    event_kind=row.event_kind,
                    identity_key=row.identity_key,
                    payment_date=row.payment_date,
                    per_unit_amount=row.per_unit_amount,
                    currency=row.currency,
                    provider_status=row.provider_status,
                    fetched_at=fetched_timestamp,
                    applied_at=applied_timestamp,
                )
                revision = list_applied_payout_revisions(session, payout.id)[-1]
            else:
                if row.applied_payout_id is None:
                    raise ValueError("revised preview row has no applied payout id")
                revision = append_applied_payout_revision(
                    session,
                    row.applied_payout_id,
                    revision_kind=AppliedPayoutRevisionKind.REVISE,
                    fetched_at=fetched_timestamp,
                    applied_at=applied_timestamp,
                    payment_date=row.payment_date,
                    per_unit_amount=row.per_unit_amount,
                    currency=row.currency,
                    source_position_snapshot_id=row.position_snapshot_id,
                    provider_status=row.provider_status,
                    lifecycle=AppliedPayoutLifecycle.ACTIVE,
                )
                payout = get_applied_payout(session, row.applied_payout_id)
                if row.provider_status is None and payout.provider_status is not None:
                    # R05-04's optional argument uses None as "preserve". For a freshly
                    # created revision in this transaction, clear both rows so R05-06 can
                    # represent a real provider-status transition to null without mutating
                    # any historical revision.
                    payout.provider_status = None
                    revision.provider_status = None
                    session.flush()

            link = None
            decision = plan.duplicate_decision
            if decision is not None:
                link = set_applied_payout_reconciliation(
                    session,
                    payout.id,
                    expected_cash_flow_id=decision.expected_cash_flow_id,
                    counting_decision=decision.counting_decision,
                )

            item_results.append(
                PayoutApplyItemResult(
                    payout_id=payout.id,
                    revision_id=revision.id,
                    revision_kind=revision.revision_kind,
                    provider=payout.provider,
                    instrument_uid=payout.provider_instrument_uid,
                    event_kind=PayoutEventKind(payout.event_kind),
                    identity_key=payout.identity_key,
                    lifecycle=payout.lifecycle,
                    total_amount_kopecks=payout.total_amount_kopecks,
                    reconciliation_id=link.id if link is not None else None,
                    counting_decision=(
                        link.counting_decision if link is not None else None
                    ),
                    expected_cash_flow_id=(
                        link.expected_cash_flow_id if link is not None else None
                    ),
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        return _failure(
            selected_count,
            PayoutApplyFailureCode.PERSISTENCE_ERROR,
            "payout apply persistence failed",
        )

    return PayoutApplyResult(
        success=True,
        selected_count=selected_count,
        items=tuple(item_results),
    )


def _build_apply_plan(
    selections: tuple[PayoutApplySelection, ...],
    fresh_rows: tuple[PayoutPreviewRow, ...],
) -> tuple[_ApplyPlan, ...] | PayoutApplyResult:
    by_identity: dict[tuple[str, str, PayoutEventKind, str], list[PayoutPreviewRow]] = {}
    for row in fresh_rows:
        if row.event_kind is None or row.identity_key is None:
            continue
        key = (row.provider, row.instrument_uid, row.event_kind, row.identity_key)
        by_identity.setdefault(key, []).append(row)

    plans: list[_ApplyPlan] = []
    selected_count = len(selections)
    for selection in selections:
        key = _selection_key(selection)
        matches = by_identity.get(key, [])
        if len(matches) != 1:
            return _preview_changed(selected_count)
        row = matches[0]
        if row.fingerprint is None or row.fingerprint != selection.fingerprint:
            return _preview_changed(selected_count)
        if row.status not in _APPLYABLE:
            return _failure(
                selected_count,
                PayoutApplyFailureCode.VALIDATION_ERROR,
                f"preview status {row.status.value} is not applyable",
            )
        if (
            row.payment_date is None
            or row.per_unit_amount is None
            or row.currency != "RUB"
            or row.position_snapshot_id is None
        ):
            return _failure(
                selected_count,
                PayoutApplyFailureCode.VALIDATION_ERROR,
                "selected payout row is incomplete",
            )

        decision = selection.manual_duplicate_decision
        if row.status is PayoutPreviewStatus.POSSIBLE_MANUAL_DUPLICATE:
            if decision is None:
                return _failure(
                    selected_count,
                    PayoutApplyFailureCode.VALIDATION_ERROR,
                    "manual duplicate decision is required",
                )
            if decision.expected_cash_flow_id not in row.manual_candidate_ids:
                return _preview_changed(selected_count)
        elif decision is not None:
            return _failure(
                selected_count,
                PayoutApplyFailureCode.VALIDATION_ERROR,
                "manual duplicate decision is only valid for duplicate preview rows",
            )

        plans.append(_ApplyPlan(row=row, duplicate_decision=decision))
    return tuple(plans)


def _selection_key(
    selection: PayoutApplySelection,
) -> tuple[str, str, PayoutEventKind, str]:
    return (
        selection.provider,
        selection.instrument_uid,
        selection.event_kind,
        selection.identity_key,
    )


def _has_duplicate_selections(selections: tuple[PayoutApplySelection, ...]) -> bool:
    keys = [_selection_key(selection) for selection in selections]
    return len(keys) != len(set(keys))


def _timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if not isinstance(timestamp, datetime):
        raise TypeError("payout apply timestamps must be datetime values")
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp


def _preview_changed(selected_count: int) -> PayoutApplyResult:
    return _failure(
        selected_count,
        PayoutApplyFailureCode.PREVIEW_CHANGED,
        "payout preview changed; refresh preview before applying",
    )


def _failure(
    selected_count: int,
    code: PayoutApplyFailureCode,
    message: str,
) -> PayoutApplyResult:
    return PayoutApplyResult(
        success=False,
        selected_count=selected_count,
        error_code=code,
        message=message,
    )
