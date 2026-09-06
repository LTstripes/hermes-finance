"""Owner-managed affirmative cash-boundary completeness evidence."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    CashBoundaryCoverage,
    CashBoundaryCoverageEvidence,
    CashBoundaryCoverageState,
    CoverageStatus,
    PerformanceScope,
)
from hermes_finance.persistence import (
    Account,
    ReportingMonth,
)
from hermes_finance.persistence import (
    CashBoundaryCoverage as CashBoundaryCoverageRecord,
)
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.reporting_months import ClosedReportingMonthError

_COVERAGE_REASON = "not_computable_external_flows_incomplete"
_DEFAULT_PROVENANCE_KIND = "owner_attestation"
ACCEPTED_AUTHORITATIVE_PROVENANCE_KINDS = frozenset({"owner_attestation"})


class CashBoundaryCoverageNotFoundError(LookupError):
    pass


def _normalize_text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} must not exceed {max_length} characters")
    return normalized


def _coerce_state(state: CashBoundaryCoverageState | str) -> CashBoundaryCoverageState:
    try:
        return CashBoundaryCoverageState(state)
    except ValueError as error:
        raise ValueError(f"unsupported cash-boundary coverage state: {state!r}") from error


def _validate_interval(covered_from: date, covered_to: date) -> None:
    if type(covered_from) is not date or type(covered_to) is not date:
        raise TypeError("covered_from and covered_to must be dates")
    if covered_to < covered_from:
        raise ValueError("covered_to must be on or after covered_from")


def _require_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"account {account_id} was not found")
    return account


def require_editable_cash_boundary_interval(
    session: Session,
    *,
    covered_from: date,
    covered_to: date,
) -> None:
    """Reject evidence writes intersecting any closed reporting period."""

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


def list_cash_boundary_coverages(
    session: Session,
    *,
    account_id: int | None = None,
) -> list[CashBoundaryCoverageRecord]:
    statement = select(CashBoundaryCoverageRecord)
    if account_id is not None:
        statement = statement.where(CashBoundaryCoverageRecord.account_id == account_id)
    return list(
        session.scalars(
            statement.order_by(
                CashBoundaryCoverageRecord.account_id,
                CashBoundaryCoverageRecord.covered_from,
                CashBoundaryCoverageRecord.covered_to,
                CashBoundaryCoverageRecord.id,
            )
        )
    )


def get_cash_boundary_coverage(session: Session, coverage_id: int) -> CashBoundaryCoverageRecord:
    coverage = session.get(CashBoundaryCoverageRecord, coverage_id)
    if coverage is None:
        raise CashBoundaryCoverageNotFoundError(
            f"cash-boundary coverage {coverage_id} was not found"
        )
    return coverage


def stage_create_cash_boundary_coverage(
    session: Session,
    *,
    account_id: int,
    covered_from: date,
    covered_to: date,
    coverage_state: CashBoundaryCoverageState | str = CashBoundaryCoverageState.COMPLETE,
    provenance_kind: str = _DEFAULT_PROVENANCE_KIND,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> CashBoundaryCoverageRecord:
    _validate_interval(covered_from, covered_to)
    require_editable_cash_boundary_interval(
        session, covered_from=covered_from, covered_to=covered_to
    )
    _require_account(session, account_id)
    normalized_state = _coerce_state(coverage_state)
    normalized_provenance = _normalize_text(provenance_kind, field="provenance_kind", max_length=64)
    normalized_reference = (
        None
        if provenance_reference is None
        else _normalize_text(provenance_reference, field="provenance_reference", max_length=128)
    )
    coverage = CashBoundaryCoverageRecord(
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


def create_cash_boundary_coverage(
    session: Session,
    **kwargs: object,
) -> CashBoundaryCoverageRecord:
    coverage = stage_create_cash_boundary_coverage(session, **kwargs)
    session.commit()
    session.refresh(coverage)
    return coverage


def attest_cash_boundary_history(
    session: Session,
    *,
    account_id: int,
    covered_from: date,
    covered_to: date,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> CashBoundaryCoverageRecord:
    """Persist the currently accepted authoritative source: owner attestation."""

    return create_cash_boundary_coverage(
        session,
        account_id=account_id,
        covered_from=covered_from,
        covered_to=covered_to,
        coverage_state=CashBoundaryCoverageState.COMPLETE,
        provenance_kind=_DEFAULT_PROVENANCE_KIND,
        provenance_reference=provenance_reference,
        notes=notes,
    )


def stage_update_cash_boundary_coverage(
    session: Session,
    coverage_id: int,
    *,
    account_id: int | None = None,
    covered_from: date | None = None,
    covered_to: date | None = None,
    coverage_state: CashBoundaryCoverageState | str | None = None,
    provenance_kind: str | None = None,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> CashBoundaryCoverageRecord:
    coverage = get_cash_boundary_coverage(session, coverage_id)
    new_from = coverage.covered_from if covered_from is None else covered_from
    new_to = coverage.covered_to if covered_to is None else covered_to
    _validate_interval(new_from, new_to)
    require_editable_cash_boundary_interval(
        session, covered_from=coverage.covered_from, covered_to=coverage.covered_to
    )
    require_editable_cash_boundary_interval(session, covered_from=new_from, covered_to=new_to)
    if account_id is not None:
        _require_account(session, account_id)
        coverage.account_id = account_id
    coverage.covered_from = new_from
    coverage.covered_to = new_to
    if coverage_state is not None:
        coverage.coverage_state = _coerce_state(coverage_state).value
    if provenance_kind is not None:
        coverage.provenance_kind = _normalize_text(
            provenance_kind, field="provenance_kind", max_length=64
        )
    if provenance_reference is not None:
        coverage.provenance_reference = _normalize_text(
            provenance_reference, field="provenance_reference", max_length=128
        )
    if notes is not None:
        coverage.notes = notes
    session.flush()
    return coverage


def update_cash_boundary_coverage(
    session: Session,
    coverage_id: int,
    **kwargs: object,
) -> CashBoundaryCoverageRecord:
    coverage = stage_update_cash_boundary_coverage(session, coverage_id, **kwargs)
    session.commit()
    session.refresh(coverage)
    return coverage


def revoke_cash_boundary_coverage(
    session: Session,
    coverage_id: int,
    *,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> CashBoundaryCoverageRecord:
    """Revoke an assertion by making its evidence explicitly UNKNOWN."""

    return update_cash_boundary_coverage(
        session,
        coverage_id,
        coverage_state=CashBoundaryCoverageState.UNKNOWN,
        provenance_kind=_DEFAULT_PROVENANCE_KIND,
        provenance_reference=provenance_reference,
        notes=notes,
    )


def _overlaps(row: CashBoundaryCoverageRecord, *, start_date: date, end_date: date) -> bool:
    return row.covered_from <= end_date and row.covered_to >= start_date


def _required_account_ids(
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[object]],
) -> tuple[int, ...]:
    if scope is PerformanceScope.ACCOUNT:
        assert account_id is not None
        rows = rows_by_account.get(account_id, [])
        return (
            (account_id,)
            if any(
                getattr(row, "include_in_returns")
                and getattr(row, "effective_from") <= end_date
                and (
                    getattr(row, "effective_to") is None
                    or getattr(row, "effective_to") >= start_date
                )
                for row in rows
            )
            else ()
        )
    return tuple(
        sorted(
            current_account_id
            for current_account_id, rows in rows_by_account.items()
            if any(
                getattr(row, "include_in_returns")
                and getattr(row, "effective_from") <= end_date
                and (
                    getattr(row, "effective_to") is None
                    or getattr(row, "effective_to") >= start_date
                )
                for row in rows
            )
        )
    )


def _account_is_covered(
    rows: list[CashBoundaryCoverageRecord],
    *,
    start_date: date,
    end_date: date,
) -> bool:
    relevant = sorted(
        (row for row in rows if _overlaps(row, start_date=start_date, end_date=end_date)),
        key=lambda row: (row.covered_from, row.covered_to, row.id),
    )
    if not relevant or any(
        row.coverage_state != CashBoundaryCoverageState.COMPLETE.value
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


def cash_boundary_coverage_for_interval(
    session: Session,
    *,
    scope: PerformanceScope | str,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[object]],
) -> CashBoundaryCoverage:
    """Assess only affirmative evidence; absence is always UNKNOWN."""

    normalized_scope = PerformanceScope(scope)
    required_ids = _required_account_ids(
        scope=normalized_scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        rows_by_account=rows_by_account,
    )
    if not required_ids:
        return CashBoundaryCoverage(
            status=CoverageStatus.COMPLETE.value,
            account_ids=(),
        )

    rows = list(
        session.scalars(
            select(CashBoundaryCoverageRecord)
            .where(
                CashBoundaryCoverageRecord.account_id.in_(required_ids),
                CashBoundaryCoverageRecord.covered_to >= start_date,
                CashBoundaryCoverageRecord.covered_from <= end_date,
            )
            .order_by(
                CashBoundaryCoverageRecord.account_id,
                CashBoundaryCoverageRecord.covered_from,
                CashBoundaryCoverageRecord.covered_to,
                CashBoundaryCoverageRecord.id,
            )
        )
    )
    rows_by_required_account: dict[int, list[CashBoundaryCoverageRecord]] = {
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
    evidence = tuple(
        CashBoundaryCoverageEvidence(
            id=row.id,
            account_id=row.account_id,
            covered_from=row.covered_from,
            covered_to=row.covered_to,
            state=CashBoundaryCoverageState(row.coverage_state),
            provenance_kind=row.provenance_kind,
            provenance_reference=row.provenance_reference,
        )
        for row in rows
    )
    reasons = (_COVERAGE_REASON,) if missing else ()
    return CashBoundaryCoverage(
        status=(CoverageStatus.UNKNOWN.value if missing else CoverageStatus.COMPLETE.value),
        account_ids=required_ids,
        evidence=evidence,
        missing_or_incomplete_account_ids=missing,
        reason_codes=reasons,
    )


# Discoverable aliases for downstream availability consumers.
assess_cash_boundary_coverage = cash_boundary_coverage_for_interval
create_cash_boundary_attestation = attest_cash_boundary_history
