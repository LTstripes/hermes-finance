"""Single Europe/Moscow calendar helper for market-data date comparisons."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _moscow_tz() -> timezone | ZoneInfo:
    try:
        return ZoneInfo("Europe/Moscow")
    except ZoneInfoNotFoundError:
        # Windows CPython has no IANA database; Moscow has been UTC+3 year-round since 2014.
        return timezone(timedelta(hours=3))


MOSCOW_TZ: Final = _moscow_tz()


def moscow_calendar_date(instant: datetime) -> date:
    """Convert a provider timestamp to the Europe/Moscow calendar date."""

    if instant.tzinfo is None:
        aware = instant.replace(tzinfo=timezone.utc)
    else:
        aware = instant
    return aware.astimezone(MOSCOW_TZ).date()
