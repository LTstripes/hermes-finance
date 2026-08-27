"""Single Europe/Moscow calendar helper for market-data date comparisons."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Final
from zoneinfo import ZoneInfo

# The IANA timezone database is supplied by the `tzdata` runtime dependency on
# platforms without a system IANA database (notably Windows CPython). We resolve
# the zone eagerly at import time and fail closed if it is genuinely missing: a
# silent UTC+3 fallback would mask an uninstalled dependency and drift from the
# canonical IANA data on any future DST/policy change.
MOSCOW_TZ: Final = ZoneInfo("Europe/Moscow")


def moscow_calendar_date(instant: datetime) -> date:
    """Convert a provider timestamp to the Europe/Moscow calendar date."""

    if instant.tzinfo is None:
        aware = instant.replace(tzinfo=timezone.utc)
    else:
        aware = instant
    return aware.astimezone(MOSCOW_TZ).date()
