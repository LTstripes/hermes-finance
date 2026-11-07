"""Cheap status of the working reporting month for the sidebar plate (#1079).

Every page renders the plate, so this read must stay away from the close
workflow, readiness, freshness and dashboard builders. It answers only which
month is being worked on and how many of the month workspace sections hold
saved facts: one SELECT for the months and one EXISTS statement for the facts.
It is presentation of row presence, not a close decision or a financial value.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from hermes_finance.domain import ReportingMonthStatus
from hermes_finance.persistence import (
    AppliedProviderPayout,
    BrokerMonthApply,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpectedCashFlow,
    ExpenseEntry,
    IncomeEntry,
    InvestmentCashFlow,
    MonthlyComment,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    SavingAllocation,
)
from hermes_finance.services.applied_payouts import AppliedPayoutLifecycle
from hermes_finance.services.reporting_months import list_reporting_months

_SAVED_ACTUAL_ORIGIN = "saved_actual_v1"


def _rows(model: type, month_id: int, *criteria: ColumnElement[bool]) -> ColumnElement[bool]:
    return exists().where(model.reporting_month_id == month_id, *criteria)


def _saved_actual(model: type, month_id: int) -> ColumnElement[bool]:
    # A cloned plan row is not a fact of this month, see month_actual_facts.
    return _rows(model, month_id, model.actual_fact_origin == _SAVED_ACTUAL_ORIGIN)


def _section_conditions(month_id: int) -> dict[str, ColumnElement[bool]]:
    """Facts behind the month workspace sections that depend on stored rows."""

    return {
        "income": _saved_actual(IncomeEntry, month_id),
        "assets": _rows(CashBalance, month_id) | _rows(DepositSnapshot, month_id),
        "liabilities": _rows(Debt, month_id) | _rows(PropertySnapshot, month_id),
        "positions": _rows(PositionSnapshot, month_id),
        "brokers": _rows(BrokerMonthApply, month_id),
        "payouts": (
            _rows(ExpectedCashFlow, month_id)
            | _rows(InvestmentCashFlow, month_id)
            | _rows(
                AppliedProviderPayout,
                month_id,
                AppliedProviderPayout.lifecycle == AppliedPayoutLifecycle.ACTIVE.value,
            )
        ),
        "budget": (
            _saved_actual(ExpenseEntry, month_id) | _saved_actual(SavingAllocation, month_id)
        ),
        "note": _rows(MonthlyComment, month_id),
    }


# Month identity and the Close decision complete the ten workspace sections.
TOTAL_STEPS = len(_section_conditions(0)) + 2


@dataclass(frozen=True, slots=True)
class MonthWorkingStatus:
    month: ReportingMonth | None
    completed_steps: int
    total_steps: int = TOTAL_STEPS


def select_working_month(months: Iterable[ReportingMonth]) -> ReportingMonth | None:
    """Newest DRAFT after the latest CLOSED report, otherwise that report.

    Mirrors ``selectNewestDraftAfterLatestClosed``, so the plate names the month
    the Close page opens automatically.
    """

    ordered = sorted(months, key=lambda item: (item.year, item.month, item.id), reverse=True)
    latest_closed = next(
        (item for item in ordered if item.status == ReportingMonthStatus.CLOSED.value), None
    )
    newest_draft = next(
        (
            item
            for item in ordered
            if item.status == ReportingMonthStatus.DRAFT.value
            and (
                latest_closed is None
                or (item.year, item.month) > (latest_closed.year, latest_closed.month)
            )
        ),
        None,
    )
    return newest_draft or latest_closed


def saved_section_facts(session: Session, month: ReportingMonth) -> dict[str, bool]:
    """Which of the ten month workspace sections hold saved facts.

    The sidebar plate and the Month checklist share this rule, so their
    "N of M" counts agree. ``general`` is the snapshot date, ``close`` the
    explicit Close decision; the rest are row presence in one statement.
    """

    conditions = _section_conditions(month.id)
    facts = session.execute(
        select(*(condition.label(name) for name, condition in conditions.items()))
    ).one()
    return {
        "general": month.snapshot_date is not None,
        **{name: bool(value) for name, value in zip(conditions, facts, strict=True)},
        "close": month.status == ReportingMonthStatus.CLOSED.value,
    }


def _completed_steps(session: Session, month: ReportingMonth) -> int:
    return sum(saved_section_facts(session, month).values())


def build_month_working_status(session: Session) -> MonthWorkingStatus:
    month = select_working_month(list_reporting_months(session))
    if month is None:
        return MonthWorkingStatus(month=None, completed_steps=0)
    return MonthWorkingStatus(month=month, completed_steps=_completed_steps(session, month))
