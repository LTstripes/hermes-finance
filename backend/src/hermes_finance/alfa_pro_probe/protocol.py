"""Loopback endpoint rules and RoutingRequest encode/decode. No network I/O."""

from __future__ import annotations

import ipaddress
import json
from typing import Final
from urllib.parse import urlparse

from hermes_finance.alfa_pro_probe.channels import DEFAULT_ENDPOINT

MAX_PAYLOAD_CHARS: Final = 512_000


class AlfaProbeEndpointError(ValueError):
    """Raised when a probe endpoint is missing or is not loopback-only."""


def validate_endpoint(endpoint: str) -> str:
    raw = endpoint.strip()
    if not raw:
        raise AlfaProbeEndpointError("endpoint is required")
    parsed = urlparse(raw)
    if parsed.scheme != "ws":
        raise AlfaProbeEndpointError("endpoint must use the documented ws:// scheme")
    if parsed.username or parsed.password:
        raise AlfaProbeEndpointError("endpoint must not include credentials")
    host = (parsed.hostname or "").strip()
    if not _is_loopback_host(host):
        raise AlfaProbeEndpointError("endpoint host must be loopback-only")
    if parsed.port is None:
        raise AlfaProbeEndpointError("endpoint must include an explicit port")
    path = parsed.path or "/"
    if parsed.query or parsed.fragment:
        raise AlfaProbeEndpointError("endpoint must not include query or fragment")
    return f"ws://{host}:{parsed.port}{path}"


def default_endpoint() -> str:
    return validate_endpoint(DEFAULT_ENDPOINT)


def encode_router_message(
    command: str,
    channel: str,
    *,
    payload: object | None = None,
    request_id: str | None = None,
) -> str:
    message: dict[str, object] = {"Command": command, "Channel": channel}
    if request_id is not None:
        message["Id"] = request_id
    if payload is not None:
        message["Payload"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def decode_router_message(raw: str) -> dict[str, object]:
    if len(raw) > MAX_PAYLOAD_CHARS:
        raise ValueError("message exceeds bounded size")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("router message must be an object")
    return parsed


def decode_payload(raw: object) -> object:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None
    if len(raw) > MAX_PAYLOAD_CHARS:
        raise ValueError("payload exceeds bounded size")
    text = raw.strip()
    if not text:
        return None
    return json.loads(text)


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
