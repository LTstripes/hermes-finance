"""Narrow typed Alfa PRO reader. No public generic send(channel, payload)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Protocol

from hermes_finance.alfa_pro_probe.channels import (
    ALLOWED_ENTITY_TYPES,
    CLIENT_ENTITY_TYPES,
    ENTITY_PRIMARY_KEY,
    ForbiddenAlfaChannel,
    assert_router_send_allowed,
    bus_channel_for_entity,
    is_order_channel,
)
from hermes_finance.alfa_pro_probe.protocol import (
    MAX_PAYLOAD_CHARS,
    decode_payload,
    decode_router_message,
    encode_router_message,
)

MAX_MESSAGES: int = 400
MAX_ROWS_PER_ENTITY: int = 500
MAX_OPERATION_ROWS: int = 2000
MAX_ASSET_KEYS: int = 100
CONNECT_TIMEOUT_S: float = 5.0
READ_TIMEOUT_S: float = 3.0
TOTAL_DEADLINE_S: float = 30.0

# Official API v2.1 §4 example for the ConnectionState snapshot request.
DOCUMENTED_CONNECTION_STATE_QUERY: Final[dict[str, object]] = {
    "Init": True,
    "Subscribe": True,
}
# Official API v2.1 §3.3 SubscribeRequest requires Type; §4 names the monitor
# ConnectionState and publishes on #ConnectionState.Bus. Used only if the
# documented typeless §4 request did not yield AuthStatus. Not a translation of
# any SubscribeResponse error code.
TYPED_CONNECTION_STATE_QUERY: Final[dict[str, object]] = {
    "Type": "ConnectionState",
    "Init": True,
    "Subscribe": True,
}
_CONNECTION_STATE_PENDING: Final = frozenset({"ConnectionState", "ConnectionStateTyped"})


class MessageTransport(Protocol):
    def send_text(self, message: str) -> None: ...

    def recv_text(self, timeout: float) -> str: ...

    def close(self) -> None: ...


@dataclass
class CollectedState:
    auth_status: int | None = None
    auth_status_source: str | None = None
    ready_to_sign: bool | None = None
    bus_only: bool = False
    bus_gated: bool = False
    entities: dict[str, dict[str, dict[str, object]]] = field(default_factory=dict)
    query_status: dict[str, str] = field(default_factory=dict)
    error_codes: dict[str, int] = field(default_factory=dict)
    entity_truncated: dict[str, bool] = field(default_factory=dict)
    routing_error: bool = False
    routing_error_code: int | None = None
    truncated: bool = False
    messages_seen: int = 0
    channels_invoked: list[str] = field(default_factory=list)
    listened: list[str] = field(default_factory=list)


class AlfaProReadonlyReader:
    """Allowlisted listen/subscribe only. Callers cannot pick an arbitrary channel."""

    def __init__(
        self,
        transport: MessageTransport,
        *,
        read_timeout: float = READ_TIMEOUT_S,
        max_messages: int = MAX_MESSAGES,
        max_rows: int = MAX_ROWS_PER_ENTITY,
        max_operation_rows: int = MAX_OPERATION_ROWS,
    ) -> None:
        self._transport = transport
        self._read_timeout = read_timeout
        self._max_messages = max_messages
        self._max_rows = max_rows
        self._max_operation_rows = max_operation_rows
        self.state = CollectedState()
        self._pending: dict[str, str] = {}

    def listen_connection_state(self) -> None:
        self._listen("#ConnectionState.Bus")

    def subscribe_connection_state(self) -> None:
        self.state.query_status.setdefault("ConnectionState", "unresolved")
        self._request(
            "#Data.Query",
            dict(DOCUMENTED_CONNECTION_STATE_QUERY),
            pending="ConnectionState",
        )

    def subscribe_connection_state_typed(self) -> None:
        self.state.query_status.setdefault("ConnectionStateTyped", "unresolved")
        self._request(
            "#Data.Query",
            dict(TYPED_CONNECTION_STATE_QUERY),
            pending="ConnectionStateTyped",
        )

    def listen_entity(self, entity_type: str) -> None:
        self._listen(bus_channel_for_entity(entity_type))

    def subscribe_entity(
        self,
        entity_type: str,
        *,
        init: bool = True,
        keys: list[int] | None = None,
    ) -> None:
        if entity_type not in ALLOWED_ENTITY_TYPES:
            raise ForbiddenAlfaChannel(f"refusing unlisted Alfa entity type: {entity_type}")
        self.state.query_status.setdefault(entity_type, "unresolved")
        payload: dict[str, object] = {"Type": entity_type, "Init": init, "Subscribe": True}
        if keys is not None:
            payload["Keys"] = keys[:MAX_ASSET_KEYS]
        self._request("#Data.Query", payload, pending=entity_type)

    def unlisten_all(self) -> None:
        for channel in list(self.state.listened):
            try:
                self._dispatch("unlisten", channel)
            except ForbiddenAlfaChannel:
                continue

    def drain(
        self,
        deadline: float,
        *,
        continue_on_idle: bool = False,
        until: Callable[[], bool] | None = None,
    ) -> None:
        while time.monotonic() < deadline and self.state.messages_seen < self._max_messages:
            if until is not None and until():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            timeout = min(self._read_timeout, remaining)
            try:
                raw = self._transport.recv_text(timeout)
            except TimeoutError:
                if continue_on_idle:
                    continue
                break
            except OSError:
                break
            self.state.messages_seen += 1
            if self.state.messages_seen >= self._max_messages:
                self.state.truncated = True
            try:
                self._ingest(raw)
            except (ValueError, TypeError, json.JSONDecodeError):
                if len(raw) > MAX_PAYLOAD_CHARS:
                    self.state.truncated = True
                    for name in self._pending.values():
                        self.state.entity_truncated[name] = True
                continue
            if until is not None and until():
                break

    def close(self) -> None:
        self._transport.close()

    def _listen(self, channel: str) -> None:
        self._dispatch("listen", channel)
        if channel not in self.state.listened:
            self.state.listened.append(channel)

    def _request(self, channel: str, payload: dict[str, object], *, pending: str) -> None:
        request_id = uuid.uuid4().hex
        self._pending[request_id] = pending
        self._dispatch("request", channel, payload=payload, request_id=request_id)

    def _dispatch(
        self,
        command: str,
        channel: str,
        *,
        payload: object | None = None,
        request_id: str | None = None,
    ) -> None:
        assert_router_send_allowed(command, channel)
        encoded = encode_router_message(command, channel, payload=payload, request_id=request_id)
        invoked = f"{command}:{channel}"
        if invoked not in self.state.channels_invoked:
            self.state.channels_invoked.append(invoked)
        self._transport.send_text(encoded)

    def _ingest(self, raw: str) -> None:
        message = decode_router_message(raw)
        command = str(message.get("Command") or "")
        channel = str(message.get("Channel") or "")
        if channel and is_order_channel(channel):
            return
        request_id = str(message.get("Id") or "")
        pending = self._pending.pop(request_id, None) if request_id else None
        router_code = _standalone_error_code(message)
        if router_code is not None:
            if pending is not None:
                self._mark_error(pending, router_code)
            else:
                self._mark_routing_error(router_code)
            return
        payload = decode_payload(message.get("Payload"))
        correlated = (
            pending is not None and command == "response" and channel in {"#Data.Query", ""}
        )
        if pending in _CONNECTION_STATE_PENDING or channel == "#ConnectionState.Bus":
            if correlated and pending is not None:
                error_code = _payload_error_code(payload)
                if error_code is not None:
                    self._mark_error(pending, error_code)
                    return
                _ingest_connection_state(self.state, payload, source="query")
                self.state.query_status[pending] = "ok"
                return
            _ingest_connection_state(self.state, payload, source="bus")
            return
        if correlated:
            error_code = _payload_error_code(payload)
            if error_code is not None:
                self._mark_error(pending, error_code)
                return
            _ingest_entity_payload(
                self.state,
                pending,
                payload,
                max_rows=self._max_for(pending),
            )
            if self.state.query_status.get(pending) != "error":
                self.state.query_status[pending] = "ok"
            return
        entity_type = _entity_type_from_channel(channel)
        if entity_type is None and isinstance(payload, dict):
            declared = payload.get("Type")
            if isinstance(declared, str) and declared in ALLOWED_ENTITY_TYPES:
                entity_type = declared
        if entity_type is None:
            return
        _ingest_entity_payload(
            self.state,
            entity_type,
            payload,
            max_rows=self._max_for(entity_type),
        )

    def _mark_error(self, name: str, code: int) -> None:
        self.state.query_status[name] = "error"
        self.state.error_codes[name] = code

    def _mark_routing_error(self, code: int) -> None:
        self.state.routing_error = True
        self.state.routing_error_code = code

    def _max_for(self, entity_type: str) -> int:
        if entity_type == "ClientOperationEntity":
            return self._max_operation_rows
        return self._max_rows


def run_connection_state_bus_session(
    reader: AlfaProReadonlyReader, *, deadline: float
) -> CollectedState:
    """Listen on #ConnectionState.Bus only. No #Data.Query and no client-data queries."""

    reader.state.bus_only = True
    reader.listen_connection_state()
    reader.drain(deadline, continue_on_idle=True)
    reader.unlisten_all()
    return reader.state


def run_bus_gated_client_session(
    reader: AlfaProReadonlyReader, *, deadline: float
) -> CollectedState:
    """Observe AuthStatus from #ConnectionState.Bus, then allowlisted client reads."""

    reader.state.bus_gated = True
    reader.listen_connection_state()
    reader.drain(
        deadline,
        continue_on_idle=True,
        until=lambda: reader.state.auth_status == 2,
    )
    if reader.state.auth_status != 2:
        reader.unlisten_all()
        return reader.state
    _collect_allowlisted_client_data(reader, deadline=deadline)
    return reader.state


def run_readonly_session(reader: AlfaProReadonlyReader, *, deadline: float) -> CollectedState:
    """Bounded connection-state then client-data reads. Never touches trading channels."""

    reader.listen_connection_state()
    reader.subscribe_connection_state()
    reader.drain(deadline)
    if reader.state.auth_status is None and time.monotonic() < deadline:
        reader.subscribe_connection_state_typed()
        reader.drain(deadline)
    if reader.state.auth_status != 2:
        return reader.state
    _collect_allowlisted_client_data(reader, deadline=deadline)
    return reader.state


def _collect_allowlisted_client_data(reader: AlfaProReadonlyReader, *, deadline: float) -> None:
    for entity_type in CLIENT_ENTITY_TYPES:
        if time.monotonic() >= deadline:
            break
        reader.listen_entity(entity_type)
        reader.subscribe_entity(entity_type, init=True)
    reader.drain(deadline)

    object_ids = position_object_ids(reader.state)
    if object_ids and time.monotonic() < deadline:
        reader.listen_entity("AssetInfoEntity")
        reader.subscribe_entity("AssetInfoEntity", init=True, keys=object_ids)
    reader.drain(deadline)
    reader.unlisten_all()


def position_object_ids(state: CollectedState) -> list[int]:
    rows = state.entities.get("ClientPositionEntity", {})
    found: list[int] = []
    seen: set[int] = set()
    for row in rows.values():
        raw = row.get("IdObject")
        if isinstance(raw, bool) or not isinstance(raw, int):
            continue
        if raw in seen:
            continue
        seen.add(raw)
        found.append(raw)
        if len(found) >= MAX_ASSET_KEYS:
            break
    return found


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _entity_type_from_channel(channel: str) -> str | None:
    prefix = "#Data.Bus."
    if not channel.startswith(prefix):
        return None
    entity_type = channel[len(prefix) :]
    if entity_type in ALLOWED_ENTITY_TYPES:
        return entity_type
    return None


def _ingest_connection_state(
    state: CollectedState,
    payload: object,
    *,
    source: str,
) -> None:
    if not isinstance(payload, dict):
        return
    states = payload.get("States")
    root = states if isinstance(states, dict) else payload
    if not isinstance(root, dict):
        return
    user = root.get("User")
    if isinstance(user, dict):
        status = _as_int(user.get("AuthStatus"))
        if status is not None:
            if state.auth_status is None:
                state.auth_status_source = source
            state.auth_status = status
    sign = root.get("SignService")
    if isinstance(sign, dict):
        ready = _as_bool(sign.get("ReadyToSign"))
        if ready is not None:
            state.ready_to_sign = ready


def _ingest_entity_payload(
    state: CollectedState,
    entity_type: str,
    payload: object,
    *,
    max_rows: int,
) -> None:
    if entity_type not in ALLOWED_ENTITY_TYPES or not isinstance(payload, dict):
        return
    rows: list[object] = []
    data = payload.get("Data")
    updated = payload.get("Updated")
    if isinstance(data, list):
        rows.extend(data)
    if isinstance(updated, list):
        rows.extend(updated)
    store = state.entities.setdefault(entity_type, {})
    key_name = ENTITY_PRIMARY_KEY[entity_type]
    deleted = payload.get("Deleted")
    if isinstance(deleted, list):
        for item in deleted:
            if not isinstance(item, dict):
                continue
            key = _row_key(item, key_name)
            if key is not None:
                store.pop(key, None)
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = _row_key(item, key_name)
        if key is None:
            continue
        if key not in store and len(store) >= max_rows:
            state.truncated = True
            state.entity_truncated[entity_type] = True
            continue
        store[key] = item


def _row_key(row: dict[str, object], key_name: str) -> str | None:
    value = row.get(key_name)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, str)):
        return str(value)
    return None


def _payload_error_code(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("Error")
    if not isinstance(error, dict):
        return None
    code = error.get("Code")
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    if code == 0:
        return None
    return code


def _standalone_error_code(message: dict[str, object]) -> int | None:
    """Documented RoutingError is {Code, Message} with no Command or Channel."""

    if message.get("Command") or message.get("Channel"):
        return None
    code = message.get("Code")
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    if code == 0:
        return None
    return code
