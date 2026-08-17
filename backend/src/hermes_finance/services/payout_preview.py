"""Read-only payout preview/diff service for R05-05."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.market_data.payout import (
    PayoutEvent,
    PayoutEventKind,
    PayoutEventStatus,
)
from hermes_finance.market_data.payout_protocol import (
    PayoutFailure,
    PayoutFetchResult,
)
from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    ExpectedCashFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.applied_payouts import compute_applied_total_kopecks

MANUAL_DUPLICATE_DATE_WINDOW_DAYS = 3

_COVERAGE_METHOD = {
    PayoutEventKind.COUPON: "GetBondCoupons",
    PayoutEventKind.DIVIDEND: "GetDividends",
    PayoutEventKind.REDEMPTION: "GetBondEvents",
}
_COVERAGE_BASIS = {
    PayoutEventKind.COUPON: "coupon_date",
    PayoutEventKind.DIVIDEND: "record_date",
    PayoutEventKind.REDEMPTION: "event_date",
}


class PayoutPreviewError(ValueError):
    """The requested preview context is invalid."""


class PayoutPreviewStatus(StrEnum):
    NEW = "new"
    UNCHANGED = "unchanged"
    REVISED = "revised"
    POSSIBLE_MANUAL_DUPLICATE = "possible_manual_duplicate"
    CANCELLED_BY_PROVIDER = "cancelled_by_provider"
    MISSING_FROM_PROVIDER = "missing_from_provider"
    TENTATIVE = "tentative"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    POSITION_GONE = "position_gone"


@dataclass(frozen=True, slots=True)
class ReconciliationPreview:
    reconciliation_id: int
    expected_cash_flow_id: int
    counting_decision: str


@dataclass(frozen=True, slots=True)
class PayoutPreviewRow:
    status: PayoutPreviewStatus
    reporting_month_id: int
    account_id: int
    instrument_id: int
    position_snapshot_id: int | None
    quantity: Decimal | None
    provider: str
    instrument_uid: str
    event_kind: PayoutEventKind | None
    identity_key: str | None
    payment_date: date | None
    per_unit_amount: Decimal | None
    currency: str | None
    total_amount_kopecks: int | None
    provider_status: str | None
    source_method: str | None
    applied_payout_id: int | None
    applied_lifecycle: str | None
    manual_candidate_ids: tuple[int, ...]
    reconciliation: ReconciliationPreview | None
    selectable: bool
    default_selected: bool
    fingerprint: str | None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class PayoutPreviewResult:
    reporting_month_id: int
    account_id: int
    instrument_id: int
    position_snapshot_id: int | None
    quantity: Decimal | None
    provider: str
    instrument_uid: str
    rows: tuple[PayoutPreviewRow, ...]


def build_payout_preview(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    position_snapshot_id: int | None,
    forecast_version: str,
    fetch_result: PayoutFetchResult,
) -> PayoutPreviewResult:
    """Build a deterministic payout preview without mutating the session."""

    version = forecast_version.strip()
    if not version:
        raise PayoutPreviewError("forecast_version must not be empty")

    with session.no_autoflush:
        month = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise PayoutPreviewError(f"reporting month {reporting_month_id} was not found")

        snapshot = _load_snapshot(
            session,
            position_snapshot_id=position_snapshot_id,
            reporting_month_id=reporting_month_id,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        applied = list(
            session.scalars(
                select(AppliedProviderPayout)
                .where(
                    AppliedProviderPayout.reporting_month_id == reporting_month_id,
                    AppliedProviderPayout.account_id == account_id,
                    AppliedProviderPayout.instrument_id == instrument_id,
                )
                .order_by(AppliedProviderPayout.id)
            )
        )
        manual = list(
            session.scalars(
                select(ExpectedCashFlow)
                .where(
                    ExpectedCashFlow.reporting_month_id == reporting_month_id,
                    ExpectedCashFlow.account_id == account_id,
                    ExpectedCashFlow.instrument_id == instrument_id,
                    ExpectedCashFlow.forecast_version == version,
                    ExpectedCashFlow.flow_type.in_(
                        (
                            PayoutEventKind.COUPON.value,
                            PayoutEventKind.DIVIDEND.value,
                            PayoutEventKind.REDEMPTION.value,
                        )
                    ),
                )
                .order_by(ExpectedCashFlow.expected_date, ExpectedCashFlow.id)
            )
        )
        reconciliation = _load_reconciliation(session, applied)

    applied_by_identity = {
        _applied_identity_key(item): item
        for item in applied
        if item.provider == fetch_result.provider
        and item.provider_instrument_uid == fetch_result.instrument_uid
    }
    reconciliation_by_payout = {
        item.applied_payout_id: item for item in reconciliation
    }

    rows: list[PayoutPreviewRow] = []
    seen_identity: set[tuple[str, str, PayoutEventKind, str]] = set()

    for event in fetch_result.events:
        identity = _event_identity_key(event)
        if identity is not None:
            seen_identity.add(identity)
        applied_item = applied_by_identity.get(identity) if identity is not None else None
        candidates = _manual_candidates(event, manual)
        link = (
            _reconciliation_preview(reconciliation_by_payout.get(applied_item.id))
            if applied_item is not None
            else None
        )
        rows.append(
            _provider_event_row(
                reporting_month_id=reporting_month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                snapshot=snapshot,
                event=event,
                applied=applied_item,
                manual_candidate_ids=candidates,
                reconciliation=link,
            )
        )

    for item in applied:
        identity = _applied_identity_key(item)
        if identity in seen_identity:
            continue
        link = _reconciliation_preview(reconciliation_by_payout.get(item.id))
        if snapshot is None:
            rows.append(
                _applied_warning_row(
                    status=PayoutPreviewStatus.POSITION_GONE,
                    item=item,
                    reporting_month_id=reporting_month_id,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    snapshot=None,
                    reconciliation=link,
                    manual_candidate_ids=_manual_candidates_for_applied(item, manual),
                    message="selected position snapshot is unavailable",
                )
            )
            continue
        if _can_infer_missing(item, fetch_result):
            rows.append(
                _applied_warning_row(
                    status=PayoutPreviewStatus.MISSING_FROM_PROVIDER,
                    item=item,
                    reporting_month_id=reporting_month_id,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    snapshot=snapshot,
                    reconciliation=link,
                    manual_candidate_ids=_manual_candidates_for_applied(item, manual),
                    message="applied event is absent from successful covered provider response",
                )
            )

    for failure in fetch_result.failures:
        rows.append(
            _failure_row(
                failure,
                reporting_month_id=reporting_month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                snapshot=snapshot,
                provider=fetch_result.provider,
                instrument_uid=fetch_result.instrument_uid,
            )
        )

    ordered = tuple(sorted(rows, key=_row_sort_key))
    return PayoutPreviewResult(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=snapshot.id if snapshot is not None else None,
        quantity=snapshot.quantity if snapshot is not None else None,
        provider=fetch_result.provider,
        instrument_uid=fetch_result.instrument_uid,
        rows=ordered,
    )


def _load_snapshot(
    session: Session,
    *,
    position_snapshot_id: int | None,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
) -> PositionSnapshot | None:
    if position_snapshot_id is None:
        return None
    snapshot = session.get(PositionSnapshot, position_snapshot_id)
    if snapshot is None:
        raise PayoutPreviewError(f"position snapshot {position_snapshot_id} was not found")
    if (
        snapshot.reporting_month_id != reporting_month_id
        or snapshot.account_id != account_id
        or snapshot.instrument_id != instrument_id
    ):
        raise PayoutPreviewError(
            "position snapshot must match reporting month, account and instrument"
        )
    return snapshot


def _load_reconciliation(
    session: Session,
    applied: list[AppliedProviderPayout],
) -> list[AppliedPayoutReconciliation]:
    ids = [item.id for item in applied]
    if not ids:
        return []
    return list(
        session.scalars(
            select(AppliedPayoutReconciliation)
            .where(AppliedPayoutReconciliation.applied_payout_id.in_(ids))
            .order_by(AppliedPayoutReconciliation.id)
        )
    )


def _provider_event_row(
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot: PositionSnapshot | None,
    event: PayoutEvent,
    applied: AppliedProviderPayout | None,
    manual_candidate_ids: tuple[int, ...],
    reconciliation: ReconciliationPreview | None,
) -> PayoutPreviewRow:
    status = _event_preview_status(
        event,
        snapshot=snapshot,
        applied=applied,
        manual_candidate_ids=manual_candidate_ids,
    )
    selectable, default_selected = _selection_defaults(status)
    total = _event_total(event, snapshot)
    fingerprint = None
    if event.identity_key is not None and snapshot is not None:
        fingerprint = _preview_fingerprint(
            reporting_month_id=reporting_month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot=snapshot,
            event=event,
            applied=applied,
            manual_candidate_ids=manual_candidate_ids,
            reconciliation=reconciliation,
        )
    return PayoutPreviewRow(
        status=status,
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=snapshot.id if snapshot is not None else None,
        quantity=snapshot.quantity if snapshot is not None else None,
        provider=event.provider,
        instrument_uid=event.instrument_uid,
        event_kind=event.event_kind,
        identity_key=event.identity_key,
        payment_date=event.payment_date,
        per_unit_amount=event.per_unit_amount,
        currency=event.currency,
        total_amount_kopecks=total,
        provider_status=event.provider_status,
        source_method=event.source_method,
        applied_payout_id=applied.id if applied is not None else None,
        applied_lifecycle=applied.lifecycle if applied is not None else None,
        manual_candidate_ids=manual_candidate_ids,
        reconciliation=reconciliation,
        selectable=selectable,
        default_selected=default_selected,
        fingerprint=fingerprint,
    )


def _event_preview_status(
    event: PayoutEvent,
    *,
    snapshot: PositionSnapshot | None,
    applied: AppliedProviderPayout | None,
    manual_candidate_ids: tuple[int, ...],
) -> PayoutPreviewStatus:
    mapped = _map_provider_status(event.status)
    if mapped is not None:
        return mapped
    if snapshot is None:
        return PayoutPreviewStatus.POSITION_GONE
    if applied is not None:
        return (
            PayoutPreviewStatus.REVISED
            if _applied_is_revised(applied, event, snapshot)
            else PayoutPreviewStatus.UNCHANGED
        )
    if manual_candidate_ids:
        return PayoutPreviewStatus.POSSIBLE_MANUAL_DUPLICATE
    return PayoutPreviewStatus.NEW


def _map_provider_status(status: PayoutEventStatus) -> PayoutPreviewStatus | None:
    mapping = {
        PayoutEventStatus.TENTATIVE: PayoutPreviewStatus.TENTATIVE,
        PayoutEventStatus.AMBIGUOUS_IDENTITY: PayoutPreviewStatus.AMBIGUOUS_IDENTITY,
        PayoutEventStatus.UNSUPPORTED: PayoutPreviewStatus.UNSUPPORTED,
        PayoutEventStatus.UNAVAILABLE: PayoutPreviewStatus.UNAVAILABLE,
        PayoutEventStatus.ERROR: PayoutPreviewStatus.ERROR,
    }
    return mapping.get(status)


def _applied_is_revised(
    applied: AppliedProviderPayout,
    event: PayoutEvent,
    snapshot: PositionSnapshot,
) -> bool:
    if event.per_unit_amount is None or event.currency is None or event.payment_date is None:
        return True
    expected_total = compute_applied_total_kopecks(event.per_unit_amount, snapshot.quantity)
    return any(
        (
            applied.lifecycle != "active",
            applied.payment_date != event.payment_date,
            _decimal_from_text(applied.per_unit_amount) != event.per_unit_amount,
            applied.currency != event.currency,
            applied.provider_status != event.provider_status,
            applied.source_position_snapshot_id != snapshot.id,
            applied.quantity != snapshot.quantity,
            applied.total_amount_kopecks != expected_total,
        )
    )


def _event_total(
    event: PayoutEvent,
    snapshot: PositionSnapshot | None,
) -> int | None:
    if snapshot is None or event.per_unit_amount is None or event.currency != "RUB":
        return None
    return compute_applied_total_kopecks(event.per_unit_amount, snapshot.quantity)


def _manual_candidates(
    event: PayoutEvent,
    manual: list[ExpectedCashFlow],
) -> tuple[int, ...]:
    if event.payment_date is None:
        return ()
    return tuple(
        row.id
        for row in manual
        if row.flow_type == event.event_kind.value
        and abs((row.expected_date - event.payment_date).days)
        <= MANUAL_DUPLICATE_DATE_WINDOW_DAYS
    )


def _manual_candidates_for_applied(
    applied: AppliedProviderPayout,
    manual: list[ExpectedCashFlow],
) -> tuple[int, ...]:
    return tuple(
        row.id
        for row in manual
        if row.flow_type == applied.event_kind
        and abs((row.expected_date - applied.payment_date).days)
        <= MANUAL_DUPLICATE_DATE_WINDOW_DAYS
    )


def _reconciliation_preview(
    item: AppliedPayoutReconciliation | None,
) -> ReconciliationPreview | None:
    if item is None:
        return None
    return ReconciliationPreview(
        reconciliation_id=item.id,
        expected_cash_flow_id=item.expected_cash_flow_id,
        counting_decision=item.counting_decision,
    )


def _can_infer_missing(
    applied: AppliedProviderPayout,
    fetch_result: PayoutFetchResult,
) -> bool:
    if (
        applied.provider != fetch_result.provider
        or applied.provider_instrument_uid != fetch_result.instrument_uid
    ):
        return False

    try:
        kind = PayoutEventKind(applied.event_kind)
    except ValueError:
        return False

    filter_date = _applied_filter_date(applied, kind)
    if filter_date is None:
        return False
    method = _COVERAGE_METHOD[kind]
    basis = _COVERAGE_BASIS[kind]

    if any(
        event.provider == applied.provider
        and event.instrument_uid == applied.provider_instrument_uid
        and event.event_kind is kind
        and event.provider_filter_basis == basis
        and event.provider_filter_date == filter_date
        and event.identity_key is None
        for event in fetch_result.events
    ):
        return False

    return any(
        item.provider == applied.provider
        and item.instrument_uid == applied.provider_instrument_uid
        and item.event_kind is kind
        and item.method == method
        and item.provider_filter_basis == basis
        and item.successful
        and item.structurally_valid
        and item.requested_from <= filter_date <= item.requested_to
        for item in fetch_result.coverage
    )


def _applied_filter_date(
    applied: AppliedProviderPayout,
    kind: PayoutEventKind,
) -> date | None:
    if kind is PayoutEventKind.COUPON:
        return applied.payment_date
    if kind is PayoutEventKind.DIVIDEND:
        return _identity_date(applied.identity_key, prefix="r:")
    if kind is PayoutEventKind.REDEMPTION:
        return _identity_date(applied.identity_key, prefix="mty-date:")
    return None


def _identity_date(identity_key: str, *, prefix: str) -> date | None:
    if not identity_key.startswith(prefix):
        return None
    value = identity_key[len(prefix) :]
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed


def _applied_warning_row(
    *,
    status: PayoutPreviewStatus,
    item: AppliedProviderPayout,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot: PositionSnapshot | None,
    reconciliation: ReconciliationPreview | None,
    manual_candidate_ids: tuple[int, ...],
    message: str,
) -> PayoutPreviewRow:
    try:
        kind = PayoutEventKind(item.event_kind)
    except ValueError as error:
        raise PayoutPreviewError(
            f"applied payout {item.id} has unsupported event kind"
        ) from error
    return PayoutPreviewRow(
        status=status,
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=item.source_position_snapshot_id,
        quantity=item.quantity,
        provider=item.provider,
        instrument_uid=item.provider_instrument_uid,
        event_kind=kind,
        identity_key=item.identity_key,
        payment_date=item.payment_date,
        per_unit_amount=_decimal_from_text(item.per_unit_amount),
        currency=item.currency,
        total_amount_kopecks=item.total_amount_kopecks,
        provider_status=item.provider_status,
        source_method=_COVERAGE_METHOD[kind],
        applied_payout_id=item.id,
        applied_lifecycle=item.lifecycle,
        manual_candidate_ids=manual_candidate_ids,
        reconciliation=reconciliation,
        selectable=False,
        default_selected=False,
        fingerprint=None,
        message=message,
    )


def _failure_row(
    failure: PayoutFailure,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot: PositionSnapshot | None,
    provider: str,
    instrument_uid: str,
) -> PayoutPreviewRow:
    status = _map_provider_status(failure.status)
    if status is None:
        raise PayoutPreviewError("unsupported provider failure status")
    return PayoutPreviewRow(
        status=status,
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=snapshot.id if snapshot is not None else None,
        quantity=snapshot.quantity if snapshot is not None else None,
        provider=provider,
        instrument_uid=instrument_uid,
        event_kind=None,
        identity_key=None,
        payment_date=None,
        per_unit_amount=None,
        currency=None,
        total_amount_kopecks=None,
        provider_status=None,
        source_method=failure.method,
        applied_payout_id=None,
        applied_lifecycle=None,
        manual_candidate_ids=(),
        reconciliation=None,
        selectable=False,
        default_selected=False,
        fingerprint=None,
        message=failure.message,
    )


def _selection_defaults(status: PayoutPreviewStatus) -> tuple[bool, bool]:
    if status is PayoutPreviewStatus.NEW:
        return True, True
    if status in {
        PayoutPreviewStatus.REVISED,
        PayoutPreviewStatus.POSSIBLE_MANUAL_DUPLICATE,
    }:
        return True, False
    return False, False


def _preview_fingerprint(
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot: PositionSnapshot,
    event: PayoutEvent,
    applied: AppliedProviderPayout | None,
    manual_candidate_ids: tuple[int, ...],
    reconciliation: ReconciliationPreview | None,
) -> str:
    payload = {
        "reporting_month_id": reporting_month_id,
        "account_id": account_id,
        "instrument_id": instrument_id,
        "position_snapshot_id": snapshot.id,
        "quantity": _canonical_decimal(snapshot.quantity),
        "provider": event.provider,
        "instrument_uid": event.instrument_uid,
        "event_kind": event.event_kind.value,
        "identity_key": event.identity_key,
        "provider_event_status": event.status.value,
        "payment_date": (
            event.payment_date.isoformat() if event.payment_date is not None else None
        ),
        "per_unit_amount": _canonical_decimal(event.per_unit_amount),
        "currency": event.currency,
        "provider_status": event.provider_status,
        "applied_payout_id": applied.id if applied is not None else None,
        "applied_lifecycle": applied.lifecycle if applied is not None else None,
        "manual_candidate_ids": list(manual_candidate_ids),
        "reconciliation": (
            {
                "expected_cash_flow_id": reconciliation.expected_cash_flow_id,
                "counting_decision": reconciliation.counting_decision,
            }
            if reconciliation is not None
            else None
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _event_identity_key(
    event: PayoutEvent,
) -> tuple[str, str, PayoutEventKind, str] | None:
    if event.identity_key is None:
        return None
    return (
        event.provider,
        event.instrument_uid,
        event.event_kind,
        event.identity_key,
    )


def _applied_identity_key(
    applied: AppliedProviderPayout,
) -> tuple[str, str, PayoutEventKind, str]:
    return (
        applied.provider,
        applied.provider_instrument_uid,
        PayoutEventKind(applied.event_kind),
        applied.identity_key,
    )


def _decimal_from_text(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise PayoutPreviewError("persisted payout amount is not an exact decimal") from error
    if not amount.is_finite():
        raise PayoutPreviewError("persisted payout amount must be finite")
    return amount


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _row_sort_key(row: PayoutPreviewRow) -> tuple[date, str, str, str, int]:
    return (
        row.payment_date or date.max,
        row.event_kind.value if row.event_kind is not None else "~",
        row.identity_key or "~",
        row.status.value,
        row.applied_payout_id or 0,
    )
