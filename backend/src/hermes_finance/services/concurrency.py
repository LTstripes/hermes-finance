"""Optimistic-concurrency guard for month-scoped snapshot updates.

When a client reads a snapshot, it receives the server-side ``updated_at``.
On PATCH, the client echoes that value via the ``If-Match`` header. The API
layer parses the header, passes it as ``expected_updated_at`` to the service
update function, and the service compares it to the current row's
``updated_at``. Any mismatch raises :class:`ConcurrencyError`, which the
unified error handler maps to HTTP 409 ``conflict``.

The comparison is exact — the client echoes the exact value it received. No
tolerance window is applied.
"""

from __future__ import annotations

from datetime import datetime


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
