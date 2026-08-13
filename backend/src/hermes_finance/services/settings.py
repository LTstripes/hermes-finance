import re
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    DEFAULT_BASE_CURRENCY,
    DEFAULT_FORMULA_VERSION,
    DEFAULT_LOCALE,
    DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
    DEFAULT_TIMEZONE,
    AppSettings,
)

_UNSET: Final = object()
_PASSIVE_INCOME_HISTORY_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_passive_income_history_start_month(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    match = _PASSIVE_INCOME_HISTORY_MONTH.fullmatch(value)
    if match is None:
        raise ValueError("passive income history start month must be YYYY-MM")
    return int(match.group(1)), int(match.group(2))


def get_or_create_settings(session: Session) -> AppSettings:
    settings = session.scalar(select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID))
    if settings is None:
        settings = AppSettings(
            id=APP_SETTINGS_ID,
            base_currency=DEFAULT_BASE_CURRENCY,
            locale=DEFAULT_LOCALE,
            timezone=DEFAULT_TIMEZONE,
            passive_income_goal_kopecks=DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
            formula_version=DEFAULT_FORMULA_VERSION,
            passive_income_history_start_month=None,
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def update_settings(
    session: Session,
    *,
    base_currency: str | None = None,
    locale: str | None = None,
    timezone: str | None = None,
    passive_income_goal: RubleAmount | None = None,
    formula_version: str | None = None,
    passive_income_history_start_month: str | None | object = _UNSET,
) -> AppSettings:
    settings = get_or_create_settings(session)

    if base_currency is not None:
        if base_currency != DEFAULT_BASE_CURRENCY:
            raise ValueError("Only RUB is supported as the base currency")
        settings.base_currency = base_currency
    if locale is not None:
        settings.locale = locale
    if timezone is not None:
        settings.timezone = timezone
    if passive_income_goal is not None:
        if passive_income_goal.kopecks < 0:
            raise ValueError("passive income goal must not be negative")
        settings.passive_income_goal_kopecks = passive_income_goal.kopecks
        from hermes_finance.services.goals import _get_or_create_main_goal

        main_goal = _get_or_create_main_goal(
            session, seed_kopecks=passive_income_goal.kopecks, commit=False
        )
        main_goal.target_value_kopecks = passive_income_goal.kopecks
    if formula_version is not None:
        settings.formula_version = formula_version
    if passive_income_history_start_month is not _UNSET:
        parse_passive_income_history_start_month(passive_income_history_start_month)
        settings.passive_income_history_start_month = passive_income_history_start_month

    session.commit()
    session.refresh(settings)
    return settings


UPDATE_SETTINGS_UNSET: Final = _UNSET
