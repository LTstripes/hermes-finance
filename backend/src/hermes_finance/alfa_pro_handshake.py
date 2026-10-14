"""Loopback Alfa PRO WebSocket handshake credential.

The public API v2.2 contract requires one HTTP header on the opening
handshake: ``Authorization: Bearer <token>``. The token is read from the
process environment at connection time. It is not accepted from API, UI,
mapping, query, or database inputs, and it is not written into exceptions,
logs, or diagnostic artifacts.

``AuthStatus==2`` on ``#ConnectionState.Bus`` remains a separate read gate.
This module only opens the socket.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from collections.abc import Mapping
from urllib.parse import urlparse

TOKEN_ENV_NAME = "HERMES_ALFA_PRO_TOKEN"
AUTHORIZATION_HEADER = "Authorization"
_BEARER_SCHEME = "Bearer"
_MAX_TOKEN_LENGTH = 2048
TOKEN_MISSING_HINT = (
    "Задайте read-only токен в HERMES_ALFA_PRO_TOKEN для процесса Hermes "
    "и перезапустите приложение."
)
TOKEN_REJECTED_MESSAGE = "Токен отклонён при подключении. Снимок не применяется."

_HANDSHAKE_ERROR_NAMES = frozenset(
    {
        "InvalidHandshake",
        "InvalidStatus",
        "InvalidStatusCode",
        "InvalidHeader",
        "InvalidHeaderFormat",
        "InvalidHeaderValue",
        "InvalidMessage",
        "InvalidURI",
        "SecurityError",
        "NegotiationError",
    }
)
_SILENT_LOGGER = logging.getLogger("hermes_finance.alfa_pro_ws")
_SILENT_LOGGER.addHandler(logging.NullHandler())
_SILENT_LOGGER.propagate = False
_SILENT_LOGGER.setLevel(logging.CRITICAL)


class AlfaLoopbackEndpointError(Exception):
    """Endpoint is not the documented loopback router. The URL is not echoed."""

    def __init__(self) -> None:
        super().__init__("invalid endpoint")

    def __repr__(self) -> str:
        return "AlfaLoopbackEndpointError()"


class AlfaTokenMissing(Exception):
    """Local read-only token is absent or not safe to send. No socket was opened."""

    def __init__(self) -> None:
        super().__init__(TOKEN_MISSING_HINT)

    def __repr__(self) -> str:
        return "AlfaTokenMissing()"


class AlfaTokenRejected(Exception):
    """Observed HTTP 401 or 403 during the handshake. Response content is dropped."""

    def __init__(self) -> None:
        super().__init__(TOKEN_REJECTED_MESSAGE)

    def __repr__(self) -> str:
        return "AlfaTokenRejected()"


class AlfaHandshakeRejected(Exception):
    """Handshake failed for a reason other than an observed 401 or 403."""

    def __init__(self) -> None:
        super().__init__("websocket handshake rejected")

    def __repr__(self) -> str:
        return "AlfaHandshakeRejected()"


def read_alfa_pro_token(environ: Mapping[str, str] | None = None) -> str | None:
    """Return a header-safe token, or None when the local secret cannot be sent."""

    source = os.environ if environ is None else environ
    raw = source.get(TOKEN_ENV_NAME)
    if not isinstance(raw, str):
        return None
    token = raw.strip()
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in token):
        return None
    return token


def open_readonly_websocket(
    endpoint: str,
    *,
    open_timeout: float,
    origin: str | None = None,
) -> object:
    """Open one loopback router socket with the documented bearer header.

    System proxy settings are ignored so the token stays on the loopback path.
    The superseded ``Authentication`` header, query tokens, and auth frames
    are not sent.
    """

    assert_loopback_endpoint(endpoint)
    token = read_alfa_pro_token()
    if token is None:
        raise AlfaTokenMissing()
    from websockets.sync.client import connect

    _SILENT_LOGGER.disabled = True
    _SILENT_LOGGER.propagate = False
    _SILENT_LOGGER.setLevel(logging.CRITICAL)
    headers = {AUTHORIZATION_HEADER: f"{_BEARER_SCHEME} {token}"}
    kwargs: dict[str, object] = {
        "additional_headers": headers,
        "open_timeout": open_timeout,
        "close_timeout": 2.0,
        "proxy": None,
        "logger": _SILENT_LOGGER,
    }
    if origin is not None:
        kwargs["origin"] = origin
    translated: BaseException | None = None
    try:
        return connect(endpoint, **kwargs)
    except AssertionError:
        raise
    except Exception as exc:
        translated = _translate_connect_error(exc)
    assert translated is not None
    translated.__cause__ = None
    translated.__context__ = None
    translated.__suppress_context__ = True
    raise translated


def assert_loopback_endpoint(endpoint: str) -> str:
    """Reject anything other than a credential-free loopback ``ws://`` URL."""

    raw = endpoint.strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").strip()
    if (
        parsed.scheme != "ws"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or not _is_loopback_host(host)
    ):
        raise AlfaLoopbackEndpointError()
    return raw


def _translate_connect_error(exc: BaseException) -> BaseException:
    status = _status_code(exc)
    if status in {401, 403}:
        return AlfaTokenRejected()
    name = type(exc).__name__
    if name in _HANDSHAKE_ERROR_NAMES or status is not None:
        return AlfaHandshakeRejected()
    if name in {"TimeoutError", "Timeout"}:
        return TimeoutError("bounded wait elapsed")
    if name == "ConnectionRefusedError":
        return ConnectionRefusedError("connection failed")
    if name == "ConnectionResetError":
        return ConnectionResetError("connection failed")
    if name == "OSError":
        return OSError("connection failed")
    return OSError("connection failed")


def _status_code(exc: BaseException) -> int | None:
    response = _attr(exc, "response")
    if response is not None:
        parsed = _as_status_code(_attr(response, "status_code"))
        if parsed is not None:
            return parsed
    return _as_status_code(_attr(exc, "status_code"))


def _attr(obj: object, name: str) -> object:
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _as_status_code(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
