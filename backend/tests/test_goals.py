from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import GoalType
from hermes_finance.persistence import Base
from hermes_finance.services.goals import (
    DEFAULT_PASSIVE_INCOME_CALCULATION_MODE,
    GoalNotFoundError,
    create_goal,
    delete_goal,
    get_goal,
    get_or_create_main_goal,
    list_goals,
    update_goal,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "goals.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def test_main_goal_is_seeded_from_settings_and_created_once(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first = get_or_create_main_goal(session)
        second = get_or_create_main_goal(session)
        assert first.id == second.id
        assert first.goal_type == GoalType.PASSIVE_INCOME.value
        assert first.target_value_kopecks == 10_000_000
        assert first.calculation_mode == DEFAULT_PASSIVE_INCOME_CALCULATION_MODE
        assert first.is_active is True
        assert len(list_goals(session)) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_goal_types_are_persisted(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
        for goal_type in GoalType:
            goal = create_goal(
                session,
                name=f"Synthetic {goal_type.value}",
                goal_type=goal_type,
                target_value="100000.00",
                calculation_mode="custom",
            )
            assert goal.goal_type == goal_type.value
        assert len(list_goals(session)) == len(list(GoalType))
    finally:
        session.close()
        database.engine.dispose()


def test_inactive_goals_are_hidden_by_default(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        active = create_goal(
            session,
            name="Synthetic Active",
            goal_type=GoalType.CAPITAL,
            target_value="100000.00",
            calculation_mode="capital_total",
        )
        inactive = create_goal(
            session,
            name="Synthetic Inactive",
            goal_type=GoalType.CAPITAL,
            target_value="200000.00",
            calculation_mode="capital_total",
            is_active=False,
        )
        assert [goal.id for goal in list_goals(session)] == [active.id]
        assert {goal.id for goal in list_goals(session, include_inactive=True)} == {
            active.id,
            inactive.id,
        }
    finally:
        session.close()
        database.engine.dispose()


def test_goal_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        goal = create_goal(
            session,
            name="  Synthetic Goal  ",
            goal_type=GoalType.EXPENSE_COVERAGE,
            target_value="100000.00",
            target_date=date(2031, 1, 1),
            calculation_mode="expense_coverage_ratio",
            notes="synthetic note",
        )
        assert goal.name == "Synthetic Goal"
        updated = update_goal(
            session,
            goal.id,
            target_value="150000.00",
            is_active=False,
            notes="updated",
        )
        assert updated.target_value_kopecks == 15_000_000
        assert updated.is_active is False
        delete_goal(session, goal.id)
        with pytest.raises(GoalNotFoundError):
            get_goal(session, goal.id)
    finally:
        session.close()
        database.engine.dispose()


def test_goal_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            create_goal(
                session,
                name="  ",
                goal_type=GoalType.CAPITAL,
                target_value="1.00",
                calculation_mode="custom",
            )
        with pytest.raises(ValueError, match="unsupported goal type"):
            create_goal(
                session,
                name="Synthetic",
                goal_type="freedom",
                target_value="1.00",
                calculation_mode="custom",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_goal(
                session,
                name="Synthetic",
                goal_type=GoalType.CAPITAL,
                target_value="-1.00",
                calculation_mode="custom",
            )
    finally:
        session.close()
        database.engine.dispose()
