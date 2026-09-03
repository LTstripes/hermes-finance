"""Read-only monthly close readiness (R07-04 / issue #136).

Readiness is advisory. Authoritative close remains ``POST /api/months/{id}/close``.
``can_close`` is derived only from hard guards that close already enforces.
This module does not call providers, write provenance, or invent required fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    Account,
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    CashBalance,
    DepositSnapshot,
    PositionSnapshot,
)
from hermes_finance.services.applied_payouts import (
    AppliedPayoutLifecycle,
    PayoutCountingDecision,
)
from hermes_finance.services.freshness_provenance import (
    FreshnessFamily,
    FreshnessProvenanceSummary,
    FreshnessSeverity,
    FreshnessStatus,
    build_freshness_provenance_summary,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.payout_calendar import PayoutCalendarSource, merged_payout_calendar
from hermes_finance.services.reporting_months import close_hard_guards, get_reporting_month
from hermes_finance.services.salary import salary_tax_snapshot_for_month
from hermes_finance.services.salary_tax_context import SalaryTaxHistoryIncompleteError


class CloseReadinessSeverity(StrEnum):
    HARD_BLOCKER = "hard_blocker"
    WARNING = "warning"
    INFO = "info"


class CloseReadinessCode(StrEnum):
    SNAPSHOT_DATE_REQUIRED = "snapshot_date_required"
    SALARY_TAX_HISTORY_INCOMPLETE = "salary_tax_history_incomplete"
    UNRESOLVED_PAYOUT_RECONCILIATION = "unresolved_payout_reconciliation"
    SECTION_EMPTY = "section_empty"
    PROVENANCE_SUMMARY = "provenance_summary"
    BACKUP_PRESENT = "backup_present"
    BACKUP_NONE = "backup_none"
    MONTH_ALREADY_CLOSED = "month_already_closed"
    ACTIVE_ACCOUNT_SNAPSHOT_MISSING = "active_account_snapshot_missing"


_SEVERITY_ORDER = {
    CloseReadinessSeverity.HARD_BLOCKER: 0,
    CloseReadinessSeverity.WARNING: 1,
    CloseReadinessSeverity.INFO: 2,
}

_SALARY_TAX_INCOMPLETE_MESSAGE = (
    "История зарплатного НДФЛ для выбранного месяца неполная: предыдущие месяцы "
    "года отсутствуют или не закрыты. Это не блокирует закрытие."
)
_UNRESOLVED_PAYOUT_MESSAGE = (
    "Есть неразрешённые совпадения ручных и провайдерских выплат. Пока действует "
    "безопасный режим «только ручные». Это не блокирует закрытие."
)
_MONTH_ALREADY_CLOSED_MESSAGE = "Месяц уже закрыт. Повторное закрытие не предлагается."
_ACTIVE_ACCOUNT_SNAPSHOT_MISSING_MESSAGE = (
    "Активный счёт, включённый в капитал, не имеет snapshot за выбранный месяц. "
    "Значение считается отсутствующим, а не нулевым; это предупреждение не блокирует закрытие."
)
_BACKUP_NONE_MESSAGE = "Резервных копий пока нет."
_SECTION_EMPTY_MESSAGE = (
    "Раздел «{title}» в этом месяце не заполнен. Пустые необязательные разделы не мешают закрытию."
)


@dataclass(frozen=True, slots=True)
class CloseReadinessItem:
    severity: CloseReadinessSeverity
    code: str
    message: str
    context: dict[str, object]


@dataclass(frozen=True, slots=True)
class CloseReadinessBackup:
    created_at: datetime
    name: str


@dataclass(frozen=True, slots=True)
class CloseReadiness:
    year: int
    month: int
    status: str
    snapshot_date: date | None
    source: str
    can_close: bool
    items: tuple[CloseReadinessItem, ...]


def _item(
    *,
    severity: CloseReadinessSeverity,
    code: str,
    message: str,
    context: dict[str, object] | None = None,
) -> CloseReadinessItem:
    return CloseReadinessItem(
        severity=severity,
        code=code,
        message=message,
        context=dict(context or {}),
    )


def _sort_items(items: list[CloseReadinessItem]) -> tuple[CloseReadinessItem, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (_SEVERITY_ORDER[item.severity], item.code, item.message),
        )
    )


def _one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, month=2, day=28)


def _hard_blocker_items(month) -> list[CloseReadinessItem]:
    return [
        _item(
            severity=CloseReadinessSeverity.HARD_BLOCKER,
            code=code,
            message=message,
        )
        for code, message in close_hard_guards(month)
    ]


def _salary_tax_items(session: Session, month) -> list[CloseReadinessItem]:
    snapshot = salary_tax_snapshot_for_month(session, month.id)
    if snapshot.history_complete:
        return []
    context: dict[str, object] = {
        "tax_year": snapshot.tax_year,
        "opening_context_available": snapshot.opening_context_available,
    }
    if SalaryTaxHistoryIncompleteError.code in snapshot.warning_codes:
        context["reason_code"] = SalaryTaxHistoryIncompleteError.code
    return [
        _item(
            severity=CloseReadinessSeverity.WARNING,
            code=CloseReadinessCode.SALARY_TAX_HISTORY_INCOMPLETE.value,
            message=_SALARY_TAX_INCOMPLETE_MESSAGE,
            context=context,
        )
    ]


def _active_account_snapshot_items(session: Session, month) -> list[CloseReadinessItem]:
    accounts = list(
        session.scalars(
            select(Account).where(
                Account.status == "active",
                Account.include_in_capital.is_(True),
            )
        )
    )
    if not accounts:
        return []
    position_account_ids = set(
        session.scalars(
            select(PositionSnapshot.account_id).where(
                PositionSnapshot.reporting_month_id == month.id
            )
        )
    )
    deposit_account_ids = set(
        session.scalars(
            select(DepositSnapshot.account_id).where(DepositSnapshot.reporting_month_id == month.id)
        )
    )
    cash_rows = list(
        session.scalars(select(CashBalance).where(CashBalance.reporting_month_id == month.id))
    )
    cash_account_ids = {row.account_id for row in cash_rows if row.account_id is not None}
    has_unassigned_cash = any(row.account_id is None for row in cash_rows)
    missing = [
        account
        for account in accounts
        if account.id not in position_account_ids
        and account.id not in deposit_account_ids
        and account.id not in cash_account_ids
        and not (account.account_type == "cash" and has_unassigned_cash)
    ]
    if not missing:
        return []
    return [
        _item(
            severity=CloseReadinessSeverity.WARNING,
            code=CloseReadinessCode.ACTIVE_ACCOUNT_SNAPSHOT_MISSING.value,
            message=_ACTIVE_ACCOUNT_SNAPSHOT_MISSING_MESSAGE,
            context={
                "account_names": sorted(account.name for account in missing),
                "count": len(missing),
            },
        )
    ]


def _freshness_items(summary: FreshnessProvenanceSummary) -> list[CloseReadinessItem]:
    items: list[CloseReadinessItem] = []
    seen_warning_codes: set[str] = set()
    for family in summary.families:
        for reason in family.reasons:
            if reason.severity is not FreshnessSeverity.WARNING:
                continue
            code = reason.code.value
            if code in seen_warning_codes:
                continue
            seen_warning_codes.add(code)
            items.append(
                _item(
                    severity=CloseReadinessSeverity.WARNING,
                    code=code,
                    message=reason.message,
                    context=_family_context(family, reason_code=code),
                )
            )
        if family.status is FreshnessStatus.MISSING:
            items.append(_missing_family_item(family))
        elif family.status is FreshnessStatus.UNKNOWN:
            reason = family.reasons[0] if family.reasons else None
            items.append(
                _item(
                    severity=CloseReadinessSeverity.INFO,
                    code=(
                        reason.code.value
                        if reason is not None
                        else CloseReadinessCode.SECTION_EMPTY.value
                    ),
                    message=(
                        reason.message
                        if reason is not None
                        else _SECTION_EMPTY_MESSAGE.format(title=family.title)
                    ),
                    context=_family_context(
                        family, reason_code=reason.code.value if reason is not None else None
                    ),
                )
            )
    providers = list(summary.providers)
    items.append(
        _item(
            severity=CloseReadinessSeverity.INFO,
            code=CloseReadinessCode.PROVENANCE_SUMMARY.value,
            message=_provenance_summary_message(summary.reporting_month.source, providers),
            context={
                "source": summary.reporting_month.source,
                "providers": providers,
                "evaluated_on": summary.evaluated_on.isoformat(),
                "quote_valuation_target_date": summary.quote_valuation_target_date.isoformat(),
            },
        )
    )
    return items


def _family_context(family: FreshnessFamily, *, reason_code: str | None) -> dict[str, object]:
    context: dict[str, object] = {
        "family_id": family.family_id.value,
        "status": family.status.value,
        "row_count": family.coverage.row_count,
        "stale_count": family.coverage.stale_count,
        "unavailable_count": family.coverage.unavailable_count,
        "missing_count": family.coverage.missing_count,
    }
    if reason_code is not None:
        context["reason_code"] = reason_code
    return context


def _missing_family_item(family: FreshnessFamily) -> CloseReadinessItem:
    reason = family.reasons[0] if family.reasons else None
    if reason is not None:
        return _item(
            severity=CloseReadinessSeverity.INFO,
            code=reason.code.value,
            message=reason.message,
            context=_family_context(family, reason_code=reason.code.value),
        )
    return _item(
        severity=CloseReadinessSeverity.INFO,
        code=CloseReadinessCode.SECTION_EMPTY.value,
        message=_SECTION_EMPTY_MESSAGE.format(title=family.title),
        context=_family_context(family, reason_code=None),
    )


def _provenance_summary_message(source: str, providers: list[str]) -> str:
    if providers:
        listed = ", ".join(providers)
        return f"Источник месяца: {source}. Провайдеры с данными в месяце: {listed}."
    return f"Источник месяца: {source}. Провайдерских данных в выбранном месяце нет."


def _unresolved_payout_items(session: Session, month) -> list[CloseReadinessItem]:
    if month.snapshot_date is None:
        return []
    calendar = merged_payout_calendar(
        session,
        reporting_month_id=month.id,
        forecast_version=DEFAULT_FORECAST_VERSION,
    )
    calendar_provider_ids = {
        item.source_id
        for bucket in calendar
        for item in bucket.items
        if item.source_kind is PayoutCalendarSource.PROVIDER
    }
    window_start = month.snapshot_date
    window_end = _one_year_after(window_start)
    payouts = list(
        session.scalars(
            select(AppliedProviderPayout).where(
                AppliedProviderPayout.reporting_month_id == month.id,
                AppliedProviderPayout.lifecycle == AppliedPayoutLifecycle.ACTIVE.value,
                AppliedProviderPayout.payment_date >= window_start,
                AppliedProviderPayout.payment_date < window_end,
            )
        )
    )
    unresolved_ids: list[int] = []
    for payout in payouts:
        if payout.id in calendar_provider_ids:
            continue
        reconciliation = session.scalar(
            select(AppliedPayoutReconciliation).where(
                AppliedPayoutReconciliation.applied_payout_id == payout.id
            )
        )
        if (
            reconciliation is not None
            and reconciliation.counting_decision == PayoutCountingDecision.COUNT_MANUAL.value
        ):
            continue
        unresolved_ids.append(payout.id)
    if not unresolved_ids:
        return []
    return [
        _item(
            severity=CloseReadinessSeverity.WARNING,
            code=CloseReadinessCode.UNRESOLVED_PAYOUT_RECONCILIATION.value,
            message=_UNRESOLVED_PAYOUT_MESSAGE,
            context={"count": len(unresolved_ids)},
        )
    ]


def _backup_items(backup: CloseReadinessBackup | None) -> list[CloseReadinessItem]:
    if backup is None:
        return [
            _item(
                severity=CloseReadinessSeverity.INFO,
                code=CloseReadinessCode.BACKUP_NONE.value,
                message=_BACKUP_NONE_MESSAGE,
            )
        ]
    created = backup.created_at.isoformat()
    return [
        _item(
            severity=CloseReadinessSeverity.INFO,
            code=CloseReadinessCode.BACKUP_PRESENT.value,
            message=f"Последняя резервная копия: {created}.",
            context={"created_at": created, "name": backup.name},
        )
    ]


def _closed_month_items(status: str) -> list[CloseReadinessItem]:
    if status != "closed":
        return []
    return [
        _item(
            severity=CloseReadinessSeverity.INFO,
            code=CloseReadinessCode.MONTH_ALREADY_CLOSED.value,
            message=_MONTH_ALREADY_CLOSED_MESSAGE,
            context={"status": status},
        )
    ]


def build_close_readiness(
    session: Session,
    month_id: int,
    *,
    today: date,
    latest_backup: CloseReadinessBackup | None = None,
    freshness_summary: FreshnessProvenanceSummary | None = None,
) -> CloseReadiness:
    """Assemble a deterministic close-readiness checklist. Read-only."""

    with session.no_autoflush:
        month = get_reporting_month(session, month_id)
        items = _hard_blocker_items(month)
        items.extend(_salary_tax_items(session, month))
        items.extend(_active_account_snapshot_items(session, month))
        if month.snapshot_date is not None:
            freshness = freshness_summary or build_freshness_provenance_summary(
                session, month.id, today=today
            )
            items.extend(_freshness_items(freshness))
        items.extend(_unresolved_payout_items(session, month))
        items.extend(_backup_items(latest_backup))
        items.extend(_closed_month_items(month.status))
        ordered = _sort_items(items)
        can_close = not any(
            item.severity is CloseReadinessSeverity.HARD_BLOCKER for item in ordered
        )
        return CloseReadiness(
            year=month.year,
            month=month.month,
            status=month.status,
            snapshot_date=month.snapshot_date,
            source=month.source,
            can_close=can_close,
            items=ordered,
        )
