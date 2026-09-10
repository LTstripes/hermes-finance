"""Month-local planned budget lines (#336).

The plan is stored separately from actual ``expense_entries`` so actuals can
never be misread as a budget. Aggregation key is the exact
``(category, expense_type)`` pair — not a foreign key; duplicate lines with
the same key are summed on both the plan and the actual side.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import ExpenseType, RubleAmount
from hermes_finance.persistence import ExpenseEntry, PlannedBudgetLine
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)


class PlannedBudgetLineNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class PlannedVsActual:
    category: str
    expense_type: str
    planned: RubleAmount
    actual: RubleAmount


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalize_amount(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _coerce_expense_type(expense_type: ExpenseType | str) -> ExpenseType:
    try:
        return ExpenseType(expense_type)
    except ValueError as error:
        raise ValueError(f"unsupported expense type: {expense_type!r}") from error


def list_planned_budget_lines(session: Session) -> list[PlannedBudgetLine]:
    return list(
        session.scalars(
            select(PlannedBudgetLine).order_by(
                PlannedBudgetLine.reporting_month_id, PlannedBudgetLine.id
            )
        )
    )


def get_planned_budget_line(session: Session, line_id: int) -> PlannedBudgetLine:
    line = session.get(PlannedBudgetLine, line_id)
    if line is None:
        raise PlannedBudgetLineNotFoundError(f"planned budget line {line_id} was not found")
    return line


def create_planned_budget_line(
    session: Session,
    *,
    reporting_month_id: int,
    category: str,
    planned_amount: RubleAmount | str,
    expense_type: ExpenseType | str,
    notes: str | None = None,
) -> PlannedBudgetLine:
    require_editable_reporting_month(session, reporting_month_id)
    line = PlannedBudgetLine(
        reporting_month_id=reporting_month_id,
        category=_normalize_text(category, field="category"),
        planned_amount_kopecks=_normalize_amount(planned_amount, field="planned_amount"),
        expense_type=_coerce_expense_type(expense_type).value,
        notes=notes,
    )
    session.add(line)
    session.commit()
    session.refresh(line)
    return line


def update_planned_budget_line(
    session: Session,
    line_id: int,
    *,
    category: str | None = None,
    planned_amount: RubleAmount | str | None = None,
    expense_type: ExpenseType | str | None = None,
    notes: str | None = None,
) -> PlannedBudgetLine:
    line = get_planned_budget_line(session, line_id)
    require_editable_child_month(session, line)
    if category is not None:
        line.category = _normalize_text(category, field="category")
    if planned_amount is not None:
        line.planned_amount_kopecks = _normalize_amount(planned_amount, field="planned_amount")
    if expense_type is not None:
        line.expense_type = _coerce_expense_type(expense_type).value
    if notes is not None:
        line.notes = notes
    session.commit()
    session.refresh(line)
    return line


def delete_planned_budget_line(session: Session, line_id: int) -> None:
    line = get_planned_budget_line(session, line_id)
    require_editable_child_month(session, line)
    session.delete(line)
    session.commit()


def _sums_by_key(session: Session, reporting_month_id: int) -> dict[tuple[str, str], int]:
    statement = (
        select(
            PlannedBudgetLine.category,
            PlannedBudgetLine.expense_type,
            func.coalesce(func.sum(PlannedBudgetLine.planned_amount_kopecks), 0),
        )
        .where(PlannedBudgetLine.reporting_month_id == reporting_month_id)
        .group_by(PlannedBudgetLine.category, PlannedBudgetLine.expense_type)
    )
    return {(row[0], row[1]): int(row[2]) for row in session.execute(statement)}


def _actuals_by_key(session: Session, reporting_month_id: int) -> dict[tuple[str, str], int]:
    statement = (
        select(
            ExpenseEntry.category,
            ExpenseEntry.expense_type,
            func.coalesce(func.sum(ExpenseEntry.amount_kopecks), 0),
        )
        .where(ExpenseEntry.reporting_month_id == reporting_month_id)
        .group_by(ExpenseEntry.category, ExpenseEntry.expense_type)
    )
    return {(row[0], row[1]): int(row[2]) for row in session.execute(statement)}


def plan_vs_actual(session: Session, reporting_month_id: int) -> list[PlannedVsActual]:
    """Group plan and actuals by exact ``(category, expense_type)``.

    Duplicate lines on either side are summed. Keys present on only one
    side are reported with a zero counterpart — never force-joined to a
    different key. Ordering is stable: ``(category, expense_type)``.
    """
    planned = _sums_by_key(session, reporting_month_id)
    actuals = _actuals_by_key(session, reporting_month_id)
    rows = [
        PlannedVsActual(
            category=category,
            expense_type=expense_type,
            planned=RubleAmount(planned.get(key, 0)),
            actual=RubleAmount(actuals.get(key, 0)),
        )
        for key in sorted(set(planned) | set(actuals))
        for category, expense_type in (key,)
    ]
    return rows
