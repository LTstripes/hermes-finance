from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.persistence import MonthlyComment, ReportingMonth
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class MonthlyCommentNotFoundError(LookupError):
    pass


def _require_reporting_month(session: Session, month_id: int) -> None:
    if session.get(ReportingMonth, month_id) is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _comments_for_month(session: Session, month_id: int) -> list[MonthlyComment]:
    return list(
        session.scalars(
            select(MonthlyComment)
            .where(MonthlyComment.reporting_month_id == month_id)
            .order_by(MonthlyComment.position, MonthlyComment.id)
        )
    )


def list_monthly_comments(session: Session, reporting_month_id: int) -> list[MonthlyComment]:
    _require_reporting_month(session, reporting_month_id)
    return _comments_for_month(session, reporting_month_id)


def get_monthly_comment(session: Session, comment_id: int) -> MonthlyComment:
    comment = session.get(MonthlyComment, comment_id)
    if comment is None:
        raise MonthlyCommentNotFoundError(f"monthly comment {comment_id} was not found")
    return comment


def create_monthly_comment(
    session: Session,
    *,
    reporting_month_id: int,
    text: str,
) -> MonthlyComment:
    _require_reporting_month(session, reporting_month_id)
    comments = _comments_for_month(session, reporting_month_id)
    next_position = (comments[-1].position + 1) if comments else 1
    comment = MonthlyComment(
        reporting_month_id=reporting_month_id,
        position=next_position,
        text=_normalize_text(text, field="text"),
    )
    session.add(comment)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("comment position conflict") from error
    session.refresh(comment)
    return comment


def update_monthly_comment(
    session: Session,
    comment_id: int,
    *,
    text: str,
) -> MonthlyComment:
    comment = get_monthly_comment(session, comment_id)
    comment.text = _normalize_text(text, field="text")
    session.commit()
    session.refresh(comment)
    return comment


def move_monthly_comment(
    session: Session,
    comment_id: int,
    *,
    new_position: int,
) -> MonthlyComment:
    comment = get_monthly_comment(session, comment_id)
    if new_position < 1:
        raise ValueError("position must be at least 1")
    comments = _comments_for_month(session, comment.reporting_month_id)
    current_index = next(i for i, item in enumerate(comments) if item.id == comment_id)
    target_index = min(new_position - 1, len(comments) - 1)
    if target_index == current_index:
        return comment
    comments.pop(current_index)
    comments.insert(target_index, comment)
    _reposition(session, comments)
    session.refresh(comment)
    return comment


def _reposition(session: Session, comments: list[MonthlyComment]) -> None:
    offset = len(comments)
    for index, item in enumerate(comments):
        item.position = index + 1 + offset
    session.flush()
    for index, item in enumerate(comments):
        item.position = index + 1
    session.commit()


def delete_monthly_comment(session: Session, comment_id: int) -> None:
    comment = get_monthly_comment(session, comment_id)
    month_id = comment.reporting_month_id
    session.delete(comment)
    session.commit()
    remaining = _comments_for_month(session, month_id)
    if remaining:
        _reposition(session, remaining)
