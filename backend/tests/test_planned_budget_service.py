"""Planned budget service contract (#336).

The plan is owner-entered intent stored separately from actual expenses.
``0`` is an explicit zero plan, never a stand-in for "not entered"; an absent
plan is simply no rows. Plan-vs-actual groups by the exact
``(category, expense_type)`` pair and never rewrites actuals.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import ExpenseType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.expenses import create_expense_entry, list_expense_entries
from hermes_finance.services.planned_budget import (
    PlannedBudgetLineNotFoundError,
    create_planned_budget_line,
    delete_planned_budget_line,
    get_planned_budget_line,
    list_planned_budget_lines,
    plan_vs_actual,
    update_planned_budget_line,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "planned-budget.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _month(session: Session) -> int:
    month = create_reporting_month(session, year=2032, month=3, snapshot_date=date(2032, 3, 15))
    return month.id


def test_plan_crud_keeps_explicit_zero(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = _month(session)
        line = create_planned_budget_line(
            session,
            reporting_month_id=month_id,
            category="Аренда",
            planned_amount="48000.00",
            expense_type=ExpenseType.MANDATORY,
            notes="офис",
        )
        assert line.planned_amount_kopecks == 4_800_000

        zero = create_planned_budget_line(
            session,
            reporting_month_id=month_id,
            category="Подписки",
            planned_amount="0.00",
            expense_type=ExpenseType.OTHER,
        )
        assert zero.planned_amount_kopecks == 0
        assert len(list_planned_budget_lines(session)) == 2

        updated = update_planned_budget_line(session, line.id, planned_amount="50000.00")
        assert updated.planned_amount_kopecks == 5_000_000

        delete_planned_budget_line(session, zero.id)
        assert len(list_planned_budget_lines(session)) == 1
        with pytest.raises(PlannedBudgetLineNotFoundError):
            get_planned_budget_line(session, zero.id)
    finally:
        session.close()
        database.engine.dispose()


def test_plan_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = _month(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_planned_budget_line(
                session,
                reporting_month_id=month_id,
                category="   ",
                planned_amount="1.00",
                expense_type=ExpenseType.MANDATORY,
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_planned_budget_line(
                session,
                reporting_month_id=month_id,
                category="Аренда",
                planned_amount="-1.00",
                expense_type=ExpenseType.MANDATORY,
            )
        with pytest.raises(ValueError, match="unsupported expense type"):
            create_planned_budget_line(
                session,
                reporting_month_id=month_id,
                category="Аренда",
                planned_amount="1.00",
                expense_type="luxury",
            )
        assert list_planned_budget_lines(session) == []
    finally:
        session.close()
        database.engine.dispose()


def test_plan_and_actuals_compare_by_exact_key(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = _month(session)
        create_planned_budget_line(
            session,
            reporting_month_id=month_id,
            category="Аренда",
            planned_amount="48000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        # Duplicate plan lines with the same key are summed, not replaced.
        create_planned_budget_line(
            session,
            reporting_month_id=month_id,
            category="Аренда",
            planned_amount="1000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        # Same category with another type is a different key, never merged.
        create_planned_budget_line(
            session,
            reporting_month_id=month_id,
            category="Аренда",
            planned_amount="7000.00",
            expense_type=ExpenseType.COMFORTABLE,
        )
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Аренда",
            amount="50000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        # Actual with no plan line still appears, with a zero plan counterpart.
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Еда",
            amount="12000.00",
            expense_type=ExpenseType.MANDATORY,
        )

        rows = plan_vs_actual(session, month_id)
        assert [(row.category, row.expense_type) for row in rows] == [
            ("Аренда", "comfortable"),
            ("Аренда", "mandatory"),
            ("Еда", "mandatory"),
        ]
        by_key = {(row.category, row.expense_type): row for row in rows}
        assert by_key[("Аренда", "mandatory")].planned == RubleAmount(4_900_000)
        assert by_key[("Аренда", "mandatory")].actual == RubleAmount(5_000_000)
        assert by_key[("Аренда", "comfortable")].planned == RubleAmount(700_000)
        assert by_key[("Аренда", "comfortable")].actual == RubleAmount(0)
        assert by_key[("Еда", "mandatory")].planned == RubleAmount(0)
        assert by_key[("Еда", "mandatory")].actual == RubleAmount(1_200_000)

        # Writing a plan never creates or mutates actual expense entries.
        assert len(list_expense_entries(session)) == 2
    finally:
        session.close()
        database.engine.dispose()


def test_comparison_is_empty_without_plan_or_actuals(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = _month(session)
        assert plan_vs_actual(session, month_id) == []
    finally:
        session.close()
        database.engine.dispose()
