"""Shared synthetic network-boundary helpers for backend tests."""

from __future__ import annotations

import httpx2


class ForbiddenTransport(httpx2.BaseTransport):
    """Fail closed if a test attempts authenticated HTTP."""

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"authenticated network must not be called: {request.url}")
