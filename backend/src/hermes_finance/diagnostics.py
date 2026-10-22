"""Privacy-safe application and Uvicorn diagnostics; no request values or tracebacks."""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from starlette.requests import Request

_scope: ContextVar[dict | None] = ContextVar("diagnostic_scope", default=None)


def route_template(scope: dict) -> str:
    return getattr(scope.get("route"), "path", "<unmatched>")


def request_route(request: Request) -> str:
    return route_template(request.scope)


class _ServerPrivacyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access":
            # Uvicorn supplies client, method, raw target, HTTP version and status.
            if isinstance(record.args, tuple) and len(record.args) == 5:
                client, method, _target, version, status = record.args
                record.args = (client, method, route_template(_scope.get() or {}), version, status)
            else:
                record.msg, record.args = "HTTP request completed", ()
        if record.exc_info:
            error_type = record.exc_info[0].__name__
            error_id = uuid.uuid4().hex
            safe_error = RuntimeError(f"{error_type} id={error_id}")
            # Keep a diagnostic exception record, without the original value,
            # cause/context chain, frames, locals or exception notes.
            record.msg, record.args = (
                "Unhandled server error class=%s id=%s",
                (error_type, error_id),
            )
            record.exc_info = (RuntimeError, safe_error, None)
            record.exc_text = None
            record.stack_info = None
        return True


def configure_private_logging() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, _ServerPrivacyFilter) for item in logger.filters):
            logger.addFilter(_ServerPrivacyFilter())


class DiagnosticContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = _scope.set(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            _scope.reset(token)
