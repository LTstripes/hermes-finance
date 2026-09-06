"""Owner-managed in-kind boundary evidence for exact performance."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    CoverageStatus,
    InKindBoundaryCoverage,
    InKindBoundaryCoverageEvidence,
    InKindBoundaryCoverageState,
    InKindMovementEvidence,
    InKindMovementKind,
    PerformanceScope,
)
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.persistence import (
    InKindBoundaryCoverage as InKindBoundaryCoverageRecord,
)
from hermes_finance.persistence import (
    InKindMovement as InKindMovementRecord,
)
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    ReportingMonthNotFoundError,
)

_COVERAGE_REASON = "not_computable_in_kind_boundary_coverage_unknown"
_MOVEMENT_REASON = "not_computable_in_kind_movement_unvalued"
_DEFAULT_PROVENANCE_KIND = "owner_attestation"
ACCEPTED_AUTHORITATIVE_PROVENANCE_KINDS = frozenset({_DEFAULT_PROVENANCE_KIND})


class InKindBoundaryCoverageNotFoundError(LookupError):
    pass


class InKindMovementNotFoundError(LookupError):
    pass


def _normalize_text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} must not exceed {max_length} characters")
    return normalized


def _coerce_state(state: InKindBoundaryCoverageState | str) -> InKindBoundaryCoverageState:
    try:
        return InKindBoundaryCoverageState(state)
    except ValueError as error:
        raise ValueError(f"unsupported in-kind boundary coverage state: {state!r}") from error


def _coerce_movement_kind(kind: InKindMovementKind | str) -> InKindMovementKind:
    try:
        return InKindMovementKind(kind)
    except ValueError as error:
        raise ValueError(f"unsupported in-kind movement kind: {kind!r}") from error


def _validate_interval(covered_from: date, covered_to: date) -> None:
    if type(covered_from) is not date or type(covered_to) is not date:
        raise TypeError("covered_from and covered_to must be dates")
    if covered_to < covered_from:
        raise ValueError("covered_to must be on or after covered_from")


def _validate_authoritative(state: InKindBoundaryCoverageState, provenance_kind: str) -> None:
    if (
        state is InKindBoundaryCoverageState.COMPLETE
        and provenance_kind not in ACCEPTED_AUTHORITATIVE_PROVENANCE_KINDS
    ):
        raise ValueError("complete in-kind coverage requires explicit owner attestation")


def _require_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"account {account_id} was not found")
    return account


def require_editable_in_kind_boundary_interval(
    session: Session,
    *,
    covered_from: date,
    covered_to: date,
) -> None:
    """Reject coverage writes intersecting any closed reporting period."""

    closed_month = session.scalar(
        select(ReportingMonth)
        .where(
            ReportingMonth.status == "closed",
            ReportingMonth.period_start <= covered_to,
            ReportingMonth.period_end >= covered_from,
        )
        .order_by(ReportingMonth.period_start, ReportingMonth.id)
    )
    if closed_month is not None:
        raise ClosedReportingMonthError("closed reporting month must be reopened before editing")


def _require_editable_movement_date(session: Session, event_date: date) -> None:
    require_editable_in_kind_boundary_interval(
        session, covered_from=event_date, covered_to=event_date
    )


def list_in_kind_boundary_coverages(
    session: Session, *, account_id: int | None = None
) -> list[InKindBoundaryCoverageRecord]:
    statement = select(InKindBoundaryCoverageRecord)
    if account_id is not None:
        statement = statement.where(InKindBoundaryCoverageRecord.account_id == account_id)
    return list(
        session.scalars(
            statement.order_by(
                InKindBoundaryCoverageRecord.account_id,
                InKindBoundaryCoverageRecord.covered_from,
                InKindBoundaryCoverageRecord.covered_to,
                InKindBoundaryCoverageRecord.id,
            )
        )
    )


def get_in_kind_boundary_coverage(
    session: Session, coverage_id: int
) -> InKindBoundaryCoverageRecord:
    coverage = session.get(InKindBoundaryCoverageRecord, coverage_id)
    if coverage is None:
        raise InKindBoundaryCoverageNotFoundError(
            f"in-kind boundary coverage {coverage_id} was not found"
        )
    return coverage


def stage_create_in_kind_boundary_coverage(
    session: Session,
    *,
    account_id: int,
    covered_from: date,
    covered_to: date,
    coverage_state: InKindBoundaryCoverageState | str = InKindBoundaryCoverageState.COMPLETE,
    provenance_kind: str = _DEFAULT_PROVENANCE_KIND,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> InKindBoundaryCoverageRecord:
    _validate_interval(covered_from, covered_to)
    require_editable_in_kind_boundary_interval(
        session, covered_from=covered_from, covered_to=covered_to
    )
    _require_account(session, account_id)
    normalized_state = _coerce_state(coverage_state)
    normalized_provenance = _normalize_text(provenance_kind, field="provenance_kind", max_length=64)
    _validate_authoritative(normalized_state, normalized_provenance)
    normalized_reference = (
        None
        if provenance_reference is None
        else _normalize_text(provenance_reference, field="provenance_reference", max_length=128)
    )
    coverage = InKindBoundaryCoverageRecord(
        account_id=account_id,
        covered_from=covered_from,
        covered_to=covered_to,
        coverage_state=normalized_state.value,
        provenance_kind=normalized_provenance,
        provenance_reference=normalized_reference,
        notes=notes,
    )
    session.add(coverage)
    session.flush()
    return coverage


def create_in_kind_boundary_coverage(
    session: Session, **kwargs: object
) -> InKindBoundaryCoverageRecord:
    coverage = stage_create_in_kind_boundary_coverage(session, **kwargs)
    session.commit()
    session.refresh(coverage)
    return coverage


def attest_in_kind_boundary_history(
    session: Session,
    *,
    account_id: int,
    covered_from: date,
    covered_to: date,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> InKindBoundaryCoverageRecord:
    """Persist the only currently accepted COMPLETE source: owner attestation."""

    return create_in_kind_boundary_coverage(
        session,
        account_id=account_id,
        covered_from=covered_from,
        covered_to=covered_to,
        coverage_state=InKindBoundaryCoverageState.COMPLETE,
        provenance_kind=_DEFAULT_PROVENANCE_KIND,
        provenance_reference=provenance_reference,
        notes=notes,
    )


def stage_update_in_kind_boundary_coverage(
    session: Session,
    coverage_id: int,
    *,
    account_id: int | None = None,
    covered_from: date | None = None,
    covered_to: date | None = None,
    coverage_state: InKindBoundaryCoverageState | str | None = None,
    provenance_kind: str | None = None,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> InKindBoundaryCoverageRecord:
    coverage = get_in_kind_boundary_coverage(session, coverage_id)
    new_from = coverage.covered_from if covered_from is None else covered_from
    new_to = coverage.covered_to if covered_to is None else covered_to
    _validate_interval(new_from, new_to)
    require_editable_in_kind_boundary_interval(
        session, covered_from=coverage.covered_from, covered_to=coverage.covered_to
    )
    require_editable_in_kind_boundary_interval(session, covered_from=new_from, covered_to=new_to)
    if account_id is not None:
        _require_account(session, account_id)
        coverage.account_id = account_id
    coverage.covered_from = new_from
    coverage.covered_to = new_to
    new_state = (
        InKindBoundaryCoverageState(coverage.coverage_state)
        if coverage_state is None
        else _coerce_state(coverage_state)
    )
    new_provenance = (
        coverage.provenance_kind
        if provenance_kind is None
        else _normalize_text(provenance_kind, field="provenance_kind", max_length=64)
    )
    _validate_authoritative(new_state, new_provenance)
    coverage.coverage_state = new_state.value
    coverage.provenance_kind = new_provenance
    if provenance_reference is not None:
        coverage.provenance_reference = _normalize_text(
            provenance_reference, field="provenance_reference", max_length=128
        )
    if notes is not None:
        coverage.notes = notes
    session.flush()
    return coverage


def update_in_kind_boundary_coverage(
    session: Session, coverage_id: int, **kwargs: object
) -> InKindBoundaryCoverageRecord:
    coverage = stage_update_in_kind_boundary_coverage(session, coverage_id, **kwargs)
    session.commit()
    session.refresh(coverage)
    return coverage


def revoke_in_kind_boundary_coverage(
    session: Session,
    coverage_id: int,
    *,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> InKindBoundaryCoverageRecord:
    return update_in_kind_boundary_coverage(
        session,
        coverage_id,
        coverage_state=InKindBoundaryCoverageState.UNKNOWN,
        provenance_kind=_DEFAULT_PROVENANCE_KIND,
        provenance_reference=provenance_reference,
        notes=notes,
    )


def list_in_kind_movements(
    session: Session, *, account_id: int | None = None
) -> list[InKindMovementRecord]:
    statement = select(InKindMovementRecord)
    if account_id is not None:
        statement = statement.where(
            (InKindMovementRecord.source_account_id == account_id)
            | (InKindMovementRecord.destination_account_id == account_id)
        )
    return list(
        session.scalars(
            statement.order_by(InKindMovementRecord.event_date, InKindMovementRecord.id)
        )
    )


def get_in_kind_movement(session: Session, movement_id: int) -> InKindMovementRecord:
    movement = session.get(InKindMovementRecord, movement_id)
    if movement is None:
        raise InKindMovementNotFoundError(f"in-kind movement {movement_id} was not found")
    return movement


def _require_reporting_month(session: Session, reporting_month_id: int) -> ReportingMonth:
    month = session.get(ReportingMonth, reporting_month_id)
    if month is None:
        raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")
    return month


def _validate_movement_accounts(
    session: Session,
    *,
    kind: InKindMovementKind,
    source_account_id: int | None,
    destination_account_id: int | None,
) -> None:
    if kind is InKindMovementKind.EXTERNAL_IN:
        if source_account_id is not None or destination_account_id is None:
            raise ValueError("external_in requires only destination_account_id")
    elif kind is InKindMovementKind.EXTERNAL_OUT:
        if source_account_id is None or destination_account_id is not None:
            raise ValueError("external_out requires only source_account_id")
    elif (
        source_account_id is None
        or destination_account_id is None
        or source_account_id == destination_account_id
    ):
        raise ValueError("internal_transfer requires two distinct account ids")
    for account_id in (source_account_id, destination_account_id):
        if account_id is not None:
            _require_account(session, account_id)


def stage_create_in_kind_movement(
    session: Session,
    *,
    reporting_month_id: int,
    event_date: date,
    movement_kind: InKindMovementKind | str,
    source_account_id: int | None = None,
    destination_account_id: int | None = None,
    instrument_id: int | None = None,
    quantity: Decimal | str | None = None,
    provenance_kind: str = _DEFAULT_PROVENANCE_KIND,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> InKindMovementRecord:
    if type(event_date) is not date:
        raise TypeError("event_date must be a date")
    month = _require_reporting_month(session, reporting_month_id)
    if not month.period_start <= event_date <= month.period_end:
        raise ValueError("event_date must be inside reporting month")
    _require_editable_movement_date(session, event_date)
    normalized_kind = _coerce_movement_kind(movement_kind)
    _validate_movement_accounts(
        session,
        kind=normalized_kind,
        source_account_id=source_account_id,
        destination_account_id=destination_account_id,
    )
    normalized_provenance = _normalize_text(provenance_kind, field="provenance_kind", max_length=64)
    if normalized_provenance not in ACCEPTED_AUTHORITATIVE_PROVENANCE_KINDS:
        raise ValueError("known in-kind movement requires explicit owner attestation")
    normalized_quantity = None if quantity is None else Decimal(str(quantity))
    if normalized_quantity is not None and normalized_quantity <= 0:
        raise ValueError("quantity must be positive when provided")
    normalized_reference = (
        None
        if provenance_reference is None
        else _normalize_text(provenance_reference, field="provenance_reference", max_length=128)
    )
    movement = InKindMovementRecord(
        reporting_month_id=reporting_month_id,
        event_date=event_date,
        source_account_id=source_account_id,
        destination_account_id=destination_account_id,
        movement_kind=normalized_kind.value,
        instrument_id=instrument_id,
        quantity=normalized_quantity,
        provenance_kind=normalized_provenance,
        provenance_reference=normalized_reference,
        notes=notes,
    )
    session.add(movement)
    session.flush()
    return movement


def create_in_kind_movement(session: Session, **kwargs: object) -> InKindMovementRecord:
    movement = stage_create_in_kind_movement(session, **kwargs)
    session.commit()
    session.refresh(movement)
    return movement


def _overlaps(row: InKindBoundaryCoverageRecord, *, start_date: date, end_date: date) -> bool:
    return row.covered_from <= end_date and row.covered_to >= start_date


def _membership_relevant(
    rows: list[AccountPerformanceScopeMembership], *, start_date: date, end_date: date
) -> bool:
    return any(
        row.include_in_returns
        and row.effective_from <= end_date
        and (row.effective_to is None or row.effective_to >= start_date)
        for row in rows
    )


def _required_account_ids(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[object]],
) -> tuple[int, ...]:
    accounts = {
        account.id: account for account in session.scalars(select(Account).order_by(Account.id))
    }
    position_history_ids = set(
        session.scalars(
            select(PositionSnapshot.account_id)
            .where(PositionSnapshot.price_date <= end_date)
            .distinct()
        )
    )
    relevant_ids = {
        current_account_id
        for current_account_id, rows in rows_by_account.items()
        if _membership_relevant(rows, start_date=start_date, end_date=end_date)
        and (
            accounts[current_account_id].account_type in {"brokerage", "iis"}
            or current_account_id in position_history_ids
        )
    }
    if scope is PerformanceScope.ACCOUNT:
        assert account_id is not None
        return (account_id,) if account_id in relevant_ids else ()
    return tuple(sorted(relevant_ids))


def _historically_in_scope_account_ids(
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[object]],
) -> tuple[int, ...]:
    if scope is PerformanceScope.ACCOUNT:
        assert account_id is not None
        return (
            (account_id,)
            if _membership_relevant(
                rows_by_account.get(account_id, []),
                start_date=start_date,
                end_date=end_date,
            )
            else ()
        )
    return tuple(
        sorted(
            current_account_id
            for current_account_id, rows in rows_by_account.items()
            if _membership_relevant(rows, start_date=start_date, end_date=end_date)
        )
    )


def _account_is_covered(
    rows: list[InKindBoundaryCoverageRecord], *, start_date: date, end_date: date
) -> bool:
    relevant = sorted(
        (row for row in rows if _overlaps(row, start_date=start_date, end_date=end_date)),
        key=lambda row: (row.covered_from, row.covered_to, row.id),
    )
    if not relevant or any(
        row.coverage_state != InKindBoundaryCoverageState.COMPLETE.value
        or row.provenance_kind not in ACCEPTED_AUTHORITATIVE_PROVENANCE_KINDS
        for row in relevant
    ):
        return False
    cursor = start_date
    previous_to: date | None = None
    for row in relevant:
        if previous_to is not None and row.covered_from <= previous_to:
            return False
        if row.covered_from > cursor:
            return False
        cursor = max(cursor, row.covered_to + timedelta(days=1))
        previous_to = row.covered_to
        if cursor > end_date:
            return True
    return False


def _movement_evidence(row: InKindMovementRecord) -> InKindMovementEvidence:
    return InKindMovementEvidence(
        id=row.id,
        reporting_month_id=row.reporting_month_id,
        event_date=row.event_date,
        source_account_id=row.source_account_id,
        destination_account_id=row.destination_account_id,
        movement_kind=InKindMovementKind(row.movement_kind),
        instrument_id=row.instrument_id,
        quantity=None if row.quantity is None else str(row.quantity),
        provenance_kind=row.provenance_kind,
        provenance_reference=row.provenance_reference,
    )


def in_kind_boundary_coverage_for_interval(
    session: Session,
    *,
    scope: PerformanceScope | str,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[object]],
) -> InKindBoundaryCoverage:
    """Assess explicit coverage and fail closed for known unvalued markers."""

    normalized_scope = PerformanceScope(scope)
    required_ids = _required_account_ids(
        session,
        scope=normalized_scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        rows_by_account=rows_by_account,
    )
    rows = (
        list(
            session.scalars(
                select(InKindBoundaryCoverageRecord)
                .where(
                    InKindBoundaryCoverageRecord.account_id.in_(required_ids),
                    InKindBoundaryCoverageRecord.covered_to >= start_date,
                    InKindBoundaryCoverageRecord.covered_from <= end_date,
                )
                .order_by(
                    InKindBoundaryCoverageRecord.account_id,
                    InKindBoundaryCoverageRecord.covered_from,
                    InKindBoundaryCoverageRecord.covered_to,
                    InKindBoundaryCoverageRecord.id,
                )
            )
        )
        if required_ids
        else []
    )
    rows_by_required_account: dict[int, list[InKindBoundaryCoverageRecord]] = {
        current_account_id: [] for current_account_id in required_ids
    }
    for row in rows:
        rows_by_required_account[row.account_id].append(row)
    missing = tuple(
        current_account_id
        for current_account_id in required_ids
        if not _account_is_covered(
            rows_by_required_account[current_account_id],
            start_date=start_date,
            end_date=end_date,
        )
    )
    historically_in_scope_ids = set(
        _historically_in_scope_account_ids(
            scope=normalized_scope,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            rows_by_account=rows_by_account,
        )
    )
    movements = (
        list(
            session.scalars(
                select(InKindMovementRecord)
                .where(
                    InKindMovementRecord.event_date >= start_date,
                    InKindMovementRecord.event_date <= end_date,
                    (
                        InKindMovementRecord.source_account_id.in_(historically_in_scope_ids)
                        | InKindMovementRecord.destination_account_id.in_(historically_in_scope_ids)
                    ),
                )
                .order_by(InKindMovementRecord.event_date, InKindMovementRecord.id)
            )
        )
        if historically_in_scope_ids
        else []
    )
    evidence = tuple(
        InKindBoundaryCoverageEvidence(
            id=row.id,
            account_id=row.account_id,
            covered_from=row.covered_from,
            covered_to=row.covered_to,
            state=InKindBoundaryCoverageState(row.coverage_state),
            provenance_kind=row.provenance_kind,
            provenance_reference=row.provenance_reference,
        )
        for row in rows
    )
    known_movements = tuple(_movement_evidence(row) for row in movements)
    reasons: set[str] = set()
    if missing:
        reasons.add(_COVERAGE_REASON)
    if known_movements:
        reasons.add(_MOVEMENT_REASON)
    return InKindBoundaryCoverage(
        status=(CoverageStatus.UNKNOWN.value if missing else CoverageStatus.COMPLETE.value),
        account_ids=required_ids,
        evidence=evidence,
        missing_or_incomplete_account_ids=missing,
        known_movements=known_movements,
        reason_codes=tuple(sorted(reasons)),
    )


assess_in_kind_boundary_coverage = in_kind_boundary_coverage_for_interval
create_in_kind_boundary_attestation = attest_in_kind_boundary_history
