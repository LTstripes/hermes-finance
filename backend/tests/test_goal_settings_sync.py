"""B19-R2 regression: goals is the single runtime source of truth for the
passive-income main goal; app_settings.passive_income_goal_kopecks is only a
seed/default. The settings API must sync the main goal transactionally, and a
direct goal update must never write back to settings.
"""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.goals import get_or_create_main_goal, update_goal
from hermes_finance.services.settings import get_or_create_settings, update_settings


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "goal-settings-sync.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def test_settings_update_creates_main_goal_from_new_value(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        update_settings(session, passive_income_goal=RubleAmount.from_api("123456.78"))

        goal = get_or_create_main_goal(session)
        assert goal.target_value_kopecks == 12_345_678
        settings = get_or_create_settings(session)
        assert settings.passive_income_goal_kopecks == 12_345_678
    finally:
        session.close()
        database.engine.dispose()


def test_settings_update_syncs_existing_main_goal(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        main_goal = get_or_create_main_goal(session)
        assert main_goal.target_value_kopecks == 10_000_000

        update_settings(session, passive_income_goal=RubleAmount.from_api("200000.00"))

        main_goal = get_or_create_main_goal(session)
        assert main_goal.target_value_kopecks == 20_000_000
    finally:
        session.close()
        database.engine.dispose()


def test_direct_goal_update_leaves_settings_seed_unchanged(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        update_settings(session, passive_income_goal=RubleAmount.from_api("123456.78"))
        main_goal = get_or_create_main_goal(session)

        update_goal(session, main_goal.id, target_value="999999.99")

        main_goal = get_or_create_main_goal(session)
        assert main_goal.target_value_kopecks == 99_999_999
        settings = get_or_create_settings(session)
        assert settings.passive_income_goal_kopecks == 12_345_678
    finally:
        session.close()
        database.engine.dispose()


def test_settings_update_without_goal_field_leaves_goal_untouched(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        main_goal = get_or_create_main_goal(session)
        assert main_goal.target_value_kopecks == 10_000_000

        update_settings(session, locale="en-US")

        main_goal = get_or_create_main_goal(session)
        assert main_goal.target_value_kopecks == 10_000_000
        settings = get_or_create_settings(session)
        assert settings.passive_income_goal_kopecks == 10_000_000
    finally:
        session.close()
        database.engine.dispose()


def test_settings_and_main_goal_persist_in_one_transaction(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        update_settings(session, passive_income_goal=RubleAmount.from_api("123456.78"))
        session.close()

        fresh_session = database.session_factory()
        try:
            settings = get_or_create_settings(fresh_session)
            goal = get_or_create_main_goal(fresh_session)
            assert settings.passive_income_goal_kopecks == 12_345_678
            assert goal.target_value_kopecks == 12_345_678
        finally:
            fresh_session.close()
    finally:
        database.engine.dispose()


def test_settings_negative_goal_rejected_before_any_mutation(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        main_goal = get_or_create_main_goal(session)
        with pytest.raises(ValueError, match="must not be negative"):
            update_settings(session, passive_income_goal=RubleAmount.from_api("-1.00"))

        main_goal = get_or_create_main_goal(session)
        assert main_goal.target_value_kopecks == 10_000_000
        settings = get_or_create_settings(session)
        assert settings.passive_income_goal_kopecks == 10_000_000
    finally:
        session.close()
        database.engine.dispose()
