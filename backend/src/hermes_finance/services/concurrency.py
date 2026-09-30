"""Optimistic-concurrency guard for month-scoped snapshot updates.

When a client reads a snapshot, it receives the server-side ``updated_at``.
On PATCH, the client echoes that value via the ``If-Match`` header. The API
layer parses the header, passes it as ``expected_updated_at`` to the service
update function, and the service includes it in the database mutation. Any
mismatch raises :class:`ConcurrencyError`, which the unified error handler
maps to HTTP 409 ``conflict``.

The comparison is exact — the client echoes the exact value it received. No
tolerance window is applied.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import Table, select, update
from sqlalchemy.orm import Session


class ConcurrencyError(RuntimeError):
    """Raised when an optimistic-concurrency check fails.

    The message includes the field name plus the expected and actual values
    so the client can identify the stale-data condition, but no financial
    payload (amounts, positions) is ever included.
    """

    def __init__(self, field: str, expected: datetime | None, actual: datetime | None) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(f"{field} mismatch: expected {expected!r}, actual {actual!r}")


def _next_updated_at(expected: datetime) -> datetime:
    now = datetime.now(UTC)
    if expected.tzinfo is None:
        now = now.replace(tzinfo=None)
    if now <= expected:
        return expected + timedelta(microseconds=1)
    return now


def atomic_compare_and_update(
    session: Session,
    *,
    table: Table,
    row_id: int,
    expected_updated_at: datetime,
    values: Mapping[str, object],
) -> datetime:
    """Update one versioned row only when its persisted version still matches.

    All source and derived values supplied by the caller are written by one SQL
    statement. A zero-row result means another transaction won; no caller value
    was persisted.
    """

    next_updated_at = _next_updated_at(expected_updated_at)
    connection = session.connection()
    result = connection.execute(
        update(table)
        .where(
            table.c.id == row_id,
            table.c.updated_at == expected_updated_at,
        )
        .values(**values, updated_at=next_updated_at)
    )
    if result.rowcount != 1:
        actual_updated_at = connection.execute(
            select(table.c.updated_at).where(table.c.id == row_id)
        ).scalar_one_or_none()
        raise ConcurrencyError("updated_at", expected_updated_at, actual_updated_at)
    return next_updated_at
