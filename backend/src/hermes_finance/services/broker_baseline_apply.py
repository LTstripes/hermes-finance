"""Owner-approved current-state baseline apply (ADR 0016 Slice B).

Wraps the existing R06-05 quantity write. Mapping confirmation, selected
quantity apply, and §8 provenance commit in one transaction and fail closed.
Does not write cash, provider prices, NKD, P&L, or closed months.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from hermes_finance.broker_data.protocol import BrokerSnapshotProvider
from hermes_finance.broker_data.reconciliation.dto import OwnerMappingInput
from hermes_finance.domain import ReportingMonthStatus
from hermes_finance.persistence import (
    BrokerBaselineApply,
    BrokerBaselineApplyItem,
    PositionSnapshot,
)
from hermes_finance.services.broker_identity_mappings import (
    BrokerIdentityMappingConflictError,
    BrokerIdentitySubjectKind,
    confirm_mapping,
)
from hermes_finance.services.broker_snapshot_apply import (
    BrokerSnapshotApplyFailureCode,
    BrokerSnapshotApplyItemResult,
    BrokerSnapshotApplyResult,
    BrokerSnapshotApplySelection,
    PreparedBrokerSnapshotApply,
    prepare_broker_snapshot_apply,
    preview_evidence_fingerprint,
    provider_positions_for_identity,
    stage_quantity_plans,
)
from hermes_finance.services.reporting_months import (
    ReportingMonthNotFoundError,
    get_reporting_month,
)


class BrokerBaselineApplyFailureCode(StrEnum):
    PREVIEW_CHANGED = BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED.value
    VALIDATION_ERROR = BrokerSnapshotApplyFailureCode.VALIDATION_ERROR.value
    PROVIDER_ERROR = BrokerSnapshotApplyFailureCode.PROVIDER_ERROR.value
    PERSISTENCE_ERROR = BrokerSnapshotApplyFailureCode.PERSISTENCE_ERROR.value
    CLOSED_MONTH = BrokerSnapshotApplyFailureCode.CLOSED_MONTH.value
    BASELINE_DATE_MISMATCH = "baseline_date_mismatch"
    IDENTITY_CONFLICT = "identity_conflict"


@dataclass(frozen=True, slots=True)
class BrokerBaselineApplyResult:
    success: bool
    selected_count: int
    items: tuple[BrokerSnapshotApplyItemResult, ...] = ()
    error_code: BrokerBaselineApplyFailureCode | None = None
    message: str | None = None
    source_as_of: datetime | None = None
    captured_at: datetime | None = None
    snapshot_status: str | None = None
    fingerprint: str | None = None
    baseline_date: date | None = None
    provenance_id: int | None = None
    confirmed_at: datetime | None = None


def apply_owner_approved_baseline(
    session: Session,
    *,
    provider: BrokerSnapshotProvider,
    reporting_month_id: int,
    baseline_date: date,
    mapping: OwnerMappingInput,
    selections: tuple[BrokerSnapshotApplySelection, ...],
) -> BrokerBaselineApplyResult:
    """Confirm identities, apply selected quantity via R06-05, persist provenance."""

    selected_count = len(selections)
    if not isinstance(baseline_date, date) or isinstance(baseline_date, datetime):
        return _failure(
            selected_count,
            BrokerBaselineApplyFailureCode.VALIDATION_ERROR,
            "baseline_date must be an explicit calendar date",
        )

    try:
        month = get_reporting_month(session, reporting_month_id)
    except ReportingMonthNotFoundError:
        return _failure(
            selected_count,
            BrokerBaselineApplyFailureCode.VALIDATION_ERROR,
            "reporting month was not found",
        )
    if month.status == ReportingMonthStatus.CLOSED.value:
        return _failure(
            selected_count,
            BrokerBaselineApplyFailureCode.CLOSED_MONTH,
            "closed reporting month must be reopened before broker snapshot apply",
        )
    if month.snapshot_date != baseline_date:
        return _failure(
            selected_count,
            BrokerBaselineApplyFailureCode.BASELINE_DATE_MISMATCH,
            "baseline_date must equal the reporting month snapshot_date",
        )

    prepared = prepare_broker_snapshot_apply(
        session,
        provider=provider,
        reporting_month_id=reporting_month_id,
        mapping=mapping,
        selections=selections,
    )
    if isinstance(prepared, BrokerSnapshotApplyResult):
        return _from_apply_failure(prepared)

    confirmed_at = datetime.now(UTC)
    try:
        _confirm_selected_identities(session, prepared)
        item_results = stage_quantity_plans(
            session,
            reporting_month_id=reporting_month_id,
            plans=prepared.plans,
        )
        provenance = _stage_provenance(
            session,
            prepared=prepared,
            reporting_month_id=reporting_month_id,
            baseline_date=baseline_date,
            confirmed_at=confirmed_at,
            items=item_results,
        )
        session.commit()
    except BrokerIdentityMappingConflictError as error:
        session.rollback()
        return _failure(
            selected_count,
            BrokerBaselineApplyFailureCode.IDENTITY_CONFLICT,
            str(error),
        )
    except ValueError as error:
        session.rollback()
        return _failure(
            selected_count,
            BrokerBaselineApplyFailureCode.VALIDATION_ERROR,
            str(error),
        )
    except Exception:
        session.rollback()
        return _failure(
            selected_count,
            BrokerBaselineApplyFailureCode.PERSISTENCE_ERROR,
            "broker baseline apply persistence failed",
        )

    for item in item_results:
        session.refresh(session.get(PositionSnapshot, item.position_snapshot_id))
    session.refresh(provenance)

    return BrokerBaselineApplyResult(
        success=True,
        selected_count=selected_count,
        items=tuple(item_results),
        source_as_of=prepared.preview.source_as_of,
        captured_at=_snapshot_captured_at(prepared),
        snapshot_status=prepared.preview.snapshot_status.value,
        fingerprint=preview_evidence_fingerprint(prepared.preview),
        baseline_date=baseline_date,
        provenance_id=provenance.id,
        confirmed_at=provenance.confirmed_at,
    )


def _snapshot_captured_at(prepared: PreparedBrokerSnapshotApply) -> datetime:
    captured = getattr(prepared.snapshot.provenance, "captured_at", None)
    if isinstance(captured, datetime):
        return captured
    return prepared.preview.captured_at


def _confirm_selected_identities(session: Session, prepared: PreparedBrokerSnapshotApply) -> None:
    preview = prepared.preview
    source_as_of = preview.source_as_of
    captured_at = _snapshot_captured_at(prepared)
    seen: set[tuple[str, str, int]] = set()
    for plan in prepared.plans:
        positions = provider_positions_for_identity(
            prepared.snapshot,
            preview,
            account_id=plan.selection.account_id,
            instrument_id=plan.selection.instrument_id,
        )
        if len(positions) != 1:
            raise ValueError("selected position identity is missing or not unique")
        position = positions[0]
        if position.is_money is True:
            raise ValueError("IsMoney rows are not quantity-baseline eligible")
        if not position.provider_account_id or not position.provider_instrument_id:
            raise ValueError("selected position is missing provider identity")
        account_key = (
            BrokerIdentitySubjectKind.ACCOUNT.value,
            position.provider_account_id,
            plan.selection.account_id,
        )
        instrument_key = (
            BrokerIdentitySubjectKind.INSTRUMENT.value,
            position.provider_instrument_id,
            plan.selection.instrument_id,
        )
        if account_key not in seen:
            confirm_mapping(
                session,
                provider=preview.provider,
                subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
                provider_identity=position.provider_account_id,
                hermes_target_id=plan.selection.account_id,
                source_as_of=source_as_of,
                captured_at=captured_at,
                commit=False,
            )
            seen.add(account_key)
        if instrument_key not in seen:
            confirm_mapping(
                session,
                provider=preview.provider,
                subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
                provider_identity=position.provider_instrument_id,
                hermes_target_id=plan.selection.instrument_id,
                observed_isin=position.isin,
                source_as_of=source_as_of,
                captured_at=captured_at,
                commit=False,
            )
            seen.add(instrument_key)


def _stage_provenance(
    session: Session,
    *,
    prepared: PreparedBrokerSnapshotApply,
    reporting_month_id: int,
    baseline_date: date,
    confirmed_at: datetime,
    items: list[BrokerSnapshotApplyItemResult],
) -> BrokerBaselineApply:
    preview = prepared.preview
    if preview.source_as_of is None:
        raise ValueError("baseline provenance requires snapshot source_as_of")
    captured_at = _snapshot_captured_at(prepared)
    compatibility = getattr(prepared.snapshot.provenance, "compatibility_fingerprint", None)
    if isinstance(compatibility, str):
        compatibility = compatibility.strip() or None
    else:
        compatibility = None
    header = BrokerBaselineApply(
        provider=preview.provider,
        reporting_month_id=reporting_month_id,
        baseline_date=baseline_date,
        source_as_of=preview.source_as_of,
        captured_at=captured_at,
        confirmed_at=confirmed_at,
        compatibility_fingerprint=compatibility,
        apply_fingerprint=preview_evidence_fingerprint(preview),
    )
    session.add(header)
    session.flush()
    for item in items:
        session.add(
            BrokerBaselineApplyItem(
                reporting_month_id=reporting_month_id,
                baseline_apply_id=header.id,
                position_snapshot_id=item.position_snapshot_id,
                action=item.action.value,
                quantity=item.quantity,
            )
        )
    session.flush()
    return header


def _from_apply_failure(result: BrokerSnapshotApplyResult) -> BrokerBaselineApplyResult:
    code = None
    if result.error_code is not None:
        code = BrokerBaselineApplyFailureCode(result.error_code.value)
    return BrokerBaselineApplyResult(
        success=False,
        selected_count=result.selected_count,
        error_code=code,
        message=result.message,
    )


def _failure(
    selected_count: int,
    code: BrokerBaselineApplyFailureCode,
    message: str,
) -> BrokerBaselineApplyResult:
    return BrokerBaselineApplyResult(
        success=False,
        selected_count=selected_count,
        error_code=code,
        message=message,
    )
