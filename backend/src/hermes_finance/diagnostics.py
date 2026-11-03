"""Privacy-safe application and Uvicorn diagnostics; no request values or tracebacks."""

from __future__ import annotations

import json
import logging
import os
import uuid
from asyncio import CancelledError
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

from fastapi.routing import iter_route_contexts
from starlette.requests import Request
from starlette.routing import Match

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


class RequestTimingMiddleware:
    """Opt-in CI timings, flushed per event so a killed request retains its start."""

    def __init__(self, app, *, log_path: Path, routes):
        self.app = app
        self.log_path = log_path
        # The pinned FastAPI keeps included routers as lazy branches. Resolve
        # effective prefixed route contexts once, without executing handlers.
        self.routes = tuple(iter_route_contexts(routes))
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def _path(self, scope):
        # Resolve only the registered template before dispatch. Never log raw
        # path/query values, including requests rejected before routing.
        partial = "<unmatched>"
        for route in self.routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return route.path or "<unmatched>"
            if match == Match.PARTIAL and partial == "<unmatched>":
                partial = route.path or "<unmatched>"
        return partial

    def _write(self, common, event, started, status, **details):
        record = {
            **common,
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": status,
            "duration_ms": (perf_counter_ns() - started) / 1_000_000,
            **details,
        }
        # Short append-only records; no long-lived file handle or buffered tail.
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = perf_counter_ns()
        common = {
            "request_id": uuid.uuid4().hex,
            "pid": os.getpid(),
            "method": scope["method"]
            if scope["method"]
            in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
            else "<other>",
            "path": self._path(scope),
        }
        status = None
        response_complete = False
        outcome = "incomplete"
        self._write(common, "start", started, status)

        async def timed_send(message):
            nonlocal status, response_complete
            if message["type"] == "http.response.start":
                status = message["status"]
                self._write(common, "response_start", started, status)
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True

        try:
            await self.app(scope, receive, timed_send)
            outcome = "completed" if response_complete else "incomplete"
        except CancelledError:
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "error"
            if status is None:
                status = 500
            raise
        finally:
            # Includes dependency/session cleanup after the response headers.
            self._write(common, "finish", started, status, outcome=outcome)
