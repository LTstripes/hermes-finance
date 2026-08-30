"""Timezone regression tests for Windows (issue #164).

On Windows CPython there is no system IANA timezone database, so
``ZoneInfo("Europe/Moscow")`` only resolves because the ``tzdata`` runtime
dependency ships the data. These tests fail closed if that dependency is
missing or the hard-coded UTC+3 fallback is reintroduced.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from hermes_finance.market_data.moscow import MOSCOW_TZ, moscow_calendar_date
from hermes_finance.persistence import DEFAULT_TIMEZONE


def test_moscow_zone_resolves_via_tzdata_without_system_iana_db() -> None:
    # Resolves to a real IANA ZoneInfo (keyed) rather than a fixed-offset tz.
    assert isinstance(MOSCOW_TZ, ZoneInfo)
    assert MOSCOW_TZ.key == "Europe/Moscow"


def test_default_timezone_is_the_moscow_iana_key() -> None:
    assert DEFAULT_TIMEZONE == "Europe/Moscow"


def test_moscow_calendar_date_uses_moscow_offset() -> None:
    # 21:00 UTC on 2026-05-15 is 00:00 MSK on 2026-05-16 (UTC+3, no DST).
    instant = datetime(2026, 5, 15, 21, 0, 0, tzinfo=timezone.utc)
    assert moscow_calendar_date(instant) == datetime(2026, 5, 16).date()


def test_moscow_calendar_date_handles_naive_utc() -> None:
    naive = datetime(2026, 5, 15, 21, 0, 0)
    assert moscow_calendar_date(naive) == datetime(2026, 5, 16).date()


def test_winter_offset_still_utc_plus_three() -> None:
    # Moscow is UTC+3 year-round; a January instant must roll the same way.
    instant = datetime(2026, 1, 31, 22, 30, 0, tzinfo=timezone.utc)
    assert moscow_calendar_date(instant) == datetime(2026, 2, 1).date()
