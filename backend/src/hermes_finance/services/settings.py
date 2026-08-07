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
        # Local import avoids a module cycle: goals imports settings for the seed.
        from hermes_finance.services.goals import _get_or_create_main_goal

        main_goal = _get_or_create_main_goal(
            session, seed_kopecks=passive_income_goal.kopecks, commit=False
        )
        main_goal.target_value_kopecks = passive_income_goal.kopecks
    if formula_version is not None:
        settings.formula_version = formula_version

    session.commit()
    session.refresh(settings)
    return settings
