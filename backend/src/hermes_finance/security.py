"""Local HTTP ingress protection for the single-user localhost application.

The application intentionally has no authentication and listens on loopback only.
Host validation protects read and write requests from DNS-rebinding style access.
Unsafe browser requests additionally require their Origin, when present, to match
the actual local Host authority. Origin-less local CLI/API clients remain valid.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("hermes_finance.security")

_LOCAL_AUTHORITY_RE = re.compile(
    r"^(?P<host>127\.0\.0\.1|localhost)(?::(?P<port>[0-9]{1,5}))?$",
    re.IGNORECASE,
)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _local_authority(value: str | None) -> tuple[str, int | None] | None:
    if value is None:
        return None
    match = _LOCAL_AUTHORITY_RE.fullmatch(value.strip())
    if match is None:
        return None
    port_text = match.group("port")
    if port_text is None:
        port = None
    else:
        port = int(port_text)
        if not 1 <= port <= 65535:
            return None
    return match.group("host").lower(), port


def _is_starlette_test_client(request: Request, host_header: str | None) -> bool:
    """Keep the app factory compatible with Starlette's synthetic TestClient host.

    A real Uvicorn request exposes the peer IP in ``scope['client']``; only
    Starlette's in-process TestClient uses the literal ``testclient`` peer.
    """

    client = request.scope.get("client")
    return bool(
        host_header == "testserver" and client and len(client) >= 1 and client[0] == "testclient"
    )


def _same_local_origin(origin: str, host_header: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False

    if parsed.scheme.lower() != "http":
        return False
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return False

    origin_authority = _local_authority(parsed.netloc)
    host_authority = _local_authority(host_header)
    return origin_authority is not None and origin_authority == host_authority


def _rejection(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": [],
            }
        },
    )


class LocalhostSecurityMiddleware(BaseHTTPMiddleware):
    """Allow only the intended local Host and same-local-origin browser writes."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        host_header = request.headers.get("host")
        local_host = _local_authority(host_header)
        if local_host is None and not _is_starlette_test_client(request, host_header):
            logger.info(
                "LocalhostSecurityMiddleware path=%s status=400 code=bad_request",
                request.url.path,
            )
            return _rejection(400, "bad_request", "Host is not allowed for this local application")

        if request.method.upper() not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and (
                host_header is None or not _same_local_origin(origin, host_header)
            ):
                logger.info(
                    "LocalhostSecurityMiddleware path=%s status=403 code=forbidden",
                    request.url.path,
                )
                return _rejection(
                    403,
                    "forbidden",
                    "Origin is not allowed for this state-changing request",
                )

            if origin is None and request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                logger.info(
                    "LocalhostSecurityMiddleware path=%s status=403 code=forbidden",
                    request.url.path,
                )
                return _rejection(
                    403,
                    "forbidden",
                    "Cross-site state-changing requests are not allowed",
                )

        return await call_next(request)
