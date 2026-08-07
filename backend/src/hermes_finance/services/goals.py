from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import GoalType, RubleAmount
from hermes_finance.persistence import Goal
from hermes_finance.services.settings import get_or_create_settings

DEFAULT_PASSIVE_INCOME_CALCULATION_MODE = "monthly_net_passive_income"


class GoalNotFoundError(LookupError):
    pass


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalize_target_value(target_value: RubleAmount | str) -> int:
    if isinstance(target_value, str):
        target_value = RubleAmount.from_api(target_value)
    if not isinstance(target_value, RubleAmount):
        raise TypeError("target_value must be RubleAmount or decimal string")
    if target_value.kopecks < 0:
        raise ValueError("target_value must not be negative")
    return target_value.kopecks


def _coerce_goal_type(goal_type: GoalType | str) -> GoalType:
    try:
        return GoalType(goal_type)
    except ValueError as error:
        raise ValueError(f"unsupported goal type: {goal_type!r}") from error


def list_goals(session: Session, *, include_inactive: bool = False) -> list[Goal]:
    statement = select(Goal).order_by(Goal.id)
    if not include_inactive:
        statement = statement.where(Goal.is_active.is_(True))
    return list(session.scalars(statement))


def get_goal(session: Session, goal_id: int) -> Goal:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise GoalNotFoundError(f"goal {goal_id} was not found")
    return goal


def _get_or_create_main_goal(session: Session, *, seed_kopecks: int, commit: bool) -> Goal:
    """Find or create the passive-income main goal without forcing a commit.

    Used both by the public ``get_or_create_main_goal`` (seed from settings,
    own transaction) and by ``settings.update_settings`` (sync target inside
    the settings transaction).
    """
    existing = session.scalar(
        select(Goal).where(Goal.goal_type == GoalType.PASSIVE_INCOME.value).limit(1)
    )
    if existing is not None:
        return existing
    goal = Goal(
        name="Пассивный доход в месяц",
        goal_type=GoalType.PASSIVE_INCOME.value,
        target_value_kopecks=seed_kopecks,
        target_date=None,
        is_active=True,
        calculation_mode=DEFAULT_PASSIVE_INCOME_CALCULATION_MODE,
        notes=None,
    )
    session.add(goal)
    if commit:
        session.commit()
        session.refresh(goal)
    return goal


def get_or_create_main_goal(session: Session) -> Goal:
    settings = get_or_create_settings(session)
    return _get_or_create_main_goal(
        session, seed_kopecks=settings.passive_income_goal_kopecks, commit=True
    )


def create_goal(
    session: Session,
    *,
    name: str,
    goal_type: GoalType | str,
    target_value: RubleAmount | str,
    target_date: date | None = None,
    is_active: bool = True,
    calculation_mode: str,
    notes: str | None = None,
) -> Goal:
    goal = Goal(
        name=_normalize_text(name, field="name"),
        goal_type=_coerce_goal_type(goal_type).value,
        target_value_kopecks=_normalize_target_value(target_value),
        target_date=target_date,
        is_active=is_active,
        calculation_mode=_normalize_text(calculation_mode, field="calculation_mode"),
        notes=notes,
    )
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


def update_goal(
    session: Session,
    goal_id: int,
    *,
    name: str | None = None,
    goal_type: GoalType | str | None = None,
    target_value: RubleAmount | str | None = None,
    target_date: date | None = None,
    is_active: bool | None = None,
    calculation_mode: str | None = None,
    notes: str | None = None,
) -> Goal:
    goal = get_goal(session, goal_id)
    if name is not None:
        goal.name = _normalize_text(name, field="name")
    if goal_type is not None:
        goal.goal_type = _coerce_goal_type(goal_type).value
    if target_value is not None:
        goal.target_value_kopecks = _normalize_target_value(target_value)
    if target_date is not None:
        goal.target_date = target_date
    if is_active is not None:
        goal.is_active = is_active
    if calculation_mode is not None:
        goal.calculation_mode = _normalize_text(calculation_mode, field="calculation_mode")
    if notes is not None:
        goal.notes = notes
    session.commit()
    session.refresh(goal)
    return goal


def delete_goal(session: Session, goal_id: int) -> None:
    goal = get_goal(session, goal_id)
    session.delete(goal)
    session.commit()
