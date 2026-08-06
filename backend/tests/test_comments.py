from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.persistence import Base
from hermes_finance.services.comments import (
    MonthlyCommentNotFoundError,
    create_monthly_comment,
    delete_monthly_comment,
    get_monthly_comment,
    list_monthly_comments,
    move_monthly_comment,
    update_monthly_comment,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "comments.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int]:
    first = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    second = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 12))
    return first.id, second.id


def test_comments_are_ordered_by_position(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        first = create_monthly_comment(session, reporting_month_id=first_id, text="first")
        second = create_monthly_comment(session, reporting_month_id=first_id, text="second")
        third = create_monthly_comment(session, reporting_month_id=first_id, text="third")
        assert [comment.id for comment in list_monthly_comments(session, first_id)] == [
            first.id,
            second.id,
            third.id,
        ]
        assert [comment.position for comment in list_monthly_comments(session, first_id)] == [
            1,
            2,
            3,
        ]
    finally:
        session.close()
        database.engine.dispose()


def test_move_reorders_and_keeps_positions_contiguous(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        first = create_monthly_comment(session, reporting_month_id=first_id, text="first")
        second = create_monthly_comment(session, reporting_month_id=first_id, text="second")
        third = create_monthly_comment(session, reporting_month_id=first_id, text="third")
        move_monthly_comment(session, third.id, new_position=1)
        comments = list_monthly_comments(session, first_id)
        assert [comment.id for comment in comments] == [third.id, first.id, second.id]
        assert [comment.position for comment in comments] == [1, 2, 3]
        move_monthly_comment(session, first.id, new_position=3)
        comments = list_monthly_comments(session, first_id)
        assert [comment.id for comment in comments] == [third.id, second.id, first.id]
        assert [comment.position for comment in comments] == [1, 2, 3]
    finally:
        session.close()
        database.engine.dispose()


def test_delete_compacts_positions(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        first = create_monthly_comment(session, reporting_month_id=first_id, text="first")
        create_monthly_comment(session, reporting_month_id=first_id, text="second")
        delete_monthly_comment(session, first.id)
        comments = list_monthly_comments(session, first_id)
        assert [comment.position for comment in comments] == [1]
        assert comments[0].text == "second"
    finally:
        session.close()
        database.engine.dispose()


def test_comments_are_scoped_to_month(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, second_id = build_environment(session)
        create_monthly_comment(session, reporting_month_id=first_id, text="may")
        create_monthly_comment(session, reporting_month_id=second_id, text="june")
        assert [comment.text for comment in list_monthly_comments(session, first_id)] == ["may"]
        assert [comment.text for comment in list_monthly_comments(session, second_id)] == ["june"]
    finally:
        session.close()
        database.engine.dispose()


def test_comment_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        comment = create_monthly_comment(session, reporting_month_id=first_id, text="  original  ")
        assert comment.text == "original"
        updated = update_monthly_comment(session, comment.id, text="updated")
        assert updated.text == "updated"
        delete_monthly_comment(session, comment.id)
        with pytest.raises(MonthlyCommentNotFoundError):
            get_monthly_comment(session, comment.id)
    finally:
        session.close()
        database.engine.dispose()


def test_comment_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_monthly_comment(session, reporting_month_id=first_id, text="   ")
        with pytest.raises(ValueError, match="at least 1"):
            comment = create_monthly_comment(session, reporting_month_id=first_id, text="only")
            move_monthly_comment(session, comment.id, new_position=0)
    finally:
        session.close()
        database.engine.dispose()
