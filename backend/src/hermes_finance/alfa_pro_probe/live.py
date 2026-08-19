"""Owner-only live transport. Imported only after explicit --live."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from hermes_finance.alfa_pro_probe.protocol import (
    DEFAULT_HANDSHAKE_ORIGIN,
    validate_handshake_origin,
)
from hermes_finance.alfa_pro_probe.reader import (
    CONNECT_TIMEOUT_S,
    READ_TIMEOUT_S,
    TOTAL_DEADLINE_S,
    AlfaProReadonlyReader,
    run_readonly_session,
)
from hermes_finance.alfa_pro_probe.report import ProbeReport, build_report, sanitize_error

HANDSHAKE_ORIGIN = DEFAULT_HANDSHAKE_ORIGIN


@dataclass(frozen=True)
class LiveConfig:
    endpoint: str
    connect_timeout: float = CONNECT_TIMEOUT_S
    read_timeout: float = READ_TIMEOUT_S
    total_deadline: float = TOTAL_DEADLINE_S
    origin_handshake_only: bool = False
    origin: str = HANDSHAKE_ORIGIN
    id_compare_store: Path | None = None


class WebsocketTransport:
    def __init__(self, socket: object) -> None:
        self._socket = socket

    def send_text(self, message: str) -> None:
        self._socket.send(message)  # type: ignore[union-attr]

    def recv_text(self, timeout: float) -> str:
        raw = self._socket.recv(timeout=timeout)  # type: ignore[union-attr]
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    def close(self) -> None:
        close = getattr(self._socket, "close", None)
        if close is not None:
            close()


def open_websocket(endpoint: str, *, origin: str | None, open_timeout: float) -> WebsocketTransport:
    from websockets.sync.client import connect

    kwargs: dict[str, object] = {"open_timeout": open_timeout, "close_timeout": 2.0}
    if origin is not None:
        kwargs["origin"] = origin
    return WebsocketTransport(connect(endpoint, **kwargs))


def run_live(config: LiveConfig) -> ProbeReport:
    if config.origin_handshake_only:
        return _run_origin_handshake(config)
    return _run_readonly_live(config)


def _run_origin_handshake(config: LiveConfig) -> ProbeReport:
    report = ProbeReport(connection="fail", foreign_origin_websocket_handshake="unresolved")
    socket: WebsocketTransport | None = None
    try:
        origin = validate_handshake_origin(config.origin)
        socket = open_websocket(
            config.endpoint,
            origin=origin,
            open_timeout=config.connect_timeout,
        )
        report.connection = "pass"
        report.foreign_origin_websocket_handshake = "accepted"
    except Exception as exc:
        report.error = sanitize_error(exc)
        if _is_handshake_rejection(exc):
            report.connection = "pass"
            report.foreign_origin_websocket_handshake = "rejected"
        else:
            report.connection = "fail"
            report.foreign_origin_websocket_handshake = "unresolved"
    finally:
        if socket is not None:
            socket.close()
    return report


def _run_readonly_live(config: LiveConfig) -> ProbeReport:
    socket: WebsocketTransport | None = None
    reader: AlfaProReadonlyReader | None = None
    try:
        socket = open_websocket(config.endpoint, origin=None, open_timeout=config.connect_timeout)
        reader = AlfaProReadonlyReader(socket, read_timeout=config.read_timeout)
        deadline = time.monotonic() + config.total_deadline
        state = run_readonly_session(reader, deadline=deadline)
        return build_report(state, connection="pass", id_compare_store=config.id_compare_store)
    except Exception as exc:
        report = ProbeReport(connection="fail", authenticated_read="fail")
        report.error = sanitize_error(exc)
        return report
    finally:
        if reader is not None:
            reader.close()
        elif socket is not None:
            socket.close()


def _is_handshake_rejection(exc: BaseException) -> bool:
    return type(exc).__name__ in {
        "InvalidHandshake",
        "InvalidStatus",
        "InvalidStatusCode",
        "InvalidHeader",
        "SecurityError",
    }
