from typing import Final

from sqlalchemy import BigInteger, CheckConstraint, Integer, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

APP_SETTINGS_ID: Final = 1
DEFAULT_BASE_CURRENCY: Final = "RUB"
DEFAULT_LOCALE: Final = "ru-RU"
DEFAULT_TIMEZONE: Final = "Europe/Moscow"
DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS: Final = 10_000_000
DEFAULT_FORMULA_VERSION: Final = "v1"


class Base(DeclarativeBase):
    pass


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint(
            f"id = {APP_SETTINGS_ID}",
            name="ck_app_settings_singleton_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=APP_SETTINGS_ID)
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_BASE_CURRENCY, server_default=text("'RUB'")
    )
    locale: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_LOCALE, server_default=text("'ru-RU'")
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default=DEFAULT_TIMEZONE, server_default=text("'Europe/Moscow'")
    )
    passive_income_goal_kopecks: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
        server_default=text(str(DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS)),
    )
    formula_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_FORMULA_VERSION, server_default=text("'v1'")
    )
