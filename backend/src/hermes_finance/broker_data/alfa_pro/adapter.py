"""Production transient read-only Alfa PRO BrokerSnapshotProvider adapter."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from hermes_finance.alfa_pro_diagnostics import (
    AlfaCompatibilityState,
    AlfaDiagnosticFailureClass,
    AlfaDiagnosticReport,
    diagnostic_for_failure,
    diagnostic_from_evaluation,
    evaluate_compatibility,
    safe_field_names,
)
from hermes_finance.broker_data.alfa_pro.channels import (
    API_DOC_VERSION,
    REQUIRED_SNAPSHOT_ENTITIES,
    ForbiddenAlfaChannel,
)
from hermes_finance.broker_data.alfa_pro.codec import (
    AlfaSnapshotEndpointError,
    default_endpoint,
    validate_endpoint,
)
from hermes_finance.broker_data.alfa_pro.mapping import (
    account_has_undocumented_kind_fields,
    normalize_account,
    normalize_cash,
    normalize_position,
    normalize_section,
    normalize_subaccount,
)
from hermes_finance.broker_data.alfa_pro.reader import (
    CONNECT_TIMEOUT_S,
    MAX_CONNECT_TIMEOUT_S,
    MAX_READ_TIMEOUT_S,
    MAX_TOTAL_DEADLINE_S,
    MIN_CONNECT_TIMEOUT_S,
    MIN_READ_TIMEOUT_S,
    MIN_TOTAL_DEADLINE_S,
    READ_TIMEOUT_S,
    TOTAL_DEADLINE_S,
    AlfaProSnapshotReader,
    CollectedState,
    MessageTransport,
    asset_info_batches_complete,
    bounded_timeout,
    positions_missing_instrument_ref,
    run_snapshot_session,
)
from hermes_finance.broker_data.dto import (
    ALFA_PRO_PROVIDER,
    BrokerSnapshot,
    SnapshotProvenance,
    SnapshotStatus,
    TimestampProvenance,
)

TransportFactory = Callable[[str, float], MessageTransport]


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


def open_websocket(endpoint: str, *, open_timeout: float) -> WebsocketTransport:
    from websockets.sync.client import connect

    return WebsocketTransport(connect(endpoint, open_timeout=open_timeout, close_timeout=2.0))


class AlfaProBrokerSnapshotProvider:
    """Owner-initiated one-shot current-state snapshot. Import opens no network."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        transport: MessageTransport | None = None,
        transport_factory: TransportFactory | None = None,
        connect_timeout: float = CONNECT_TIMEOUT_S,
        read_timeout: float = READ_TIMEOUT_S,
        total_deadline: float = TOTAL_DEADLINE_S,
    ) -> None:
        self._endpoint = validate_endpoint(endpoint or default_endpoint())
        self._transport = transport
        self._transport_factory = transport_factory or (
            lambda url, timeout: open_websocket(url, open_timeout=timeout)
        )
        self._connect_timeout = bounded_timeout(
            "connect_timeout",
            connect_timeout,
            minimum=MIN_CONNECT_TIMEOUT_S,
            maximum=MAX_CONNECT_TIMEOUT_S,
        )
        self._read_timeout = bounded_timeout(
            "read_timeout",
            read_timeout,
            minimum=MIN_READ_TIMEOUT_S,
            maximum=MAX_READ_TIMEOUT_S,
        )
        self._total_deadline = bounded_timeout(
            "total_deadline",
            total_deadline,
            minimum=MIN_TOTAL_DEADLINE_S,
            maximum=MAX_TOTAL_DEADLINE_S,
        )

    def fetch_snapshot(self) -> BrokerSnapshot:
        captured_at = datetime.now().astimezone()
        owned_transport = False
        transport = self._transport
        reader: AlfaProSnapshotReader | None = None
        try:
            if transport is None:
                transport = self._transport_factory(self._endpoint, self._connect_timeout)
                owned_transport = True
            reader = AlfaProSnapshotReader(transport, read_timeout=self._read_timeout)
            state = run_snapshot_session(reader, deadline=time.monotonic() + self._total_deadline)
            return build_snapshot(state, captured_at=captured_at)
        except AlfaSnapshotEndpointError as exc:
            return _empty_snapshot(
                captured_at,
                SnapshotStatus.PROVIDER_UNAVAILABLE,
                sanitize_error(exc),
                failure_class=AlfaDiagnosticFailureClass.CONNECTION,
                failure_code="endpoint_rejected",
            )
        except ForbiddenAlfaChannel as exc:
            return _empty_snapshot(
                captured_at,
                SnapshotStatus.COMPATIBILITY_ERROR,
                sanitize_error(exc),
                failure_class=AlfaDiagnosticFailureClass.PROTOCOL,
                failure_code="forbidden_channel",
            )
        except Exception as exc:
            status = SnapshotStatus.PROVIDER_UNAVAILABLE
            failure_class = AlfaDiagnosticFailureClass.CONNECTION
            failure_code = "transport_failed"
            if type(exc).__name__ in {
                "InvalidHandshake",
                "InvalidStatus",
                "InvalidStatusCode",
                "InvalidHeader",
            }:
                status = SnapshotStatus.COMPATIBILITY_ERROR
                failure_class = AlfaDiagnosticFailureClass.PROTOCOL
                failure_code = "websocket_handshake_rejected"
            return _empty_snapshot(
                captured_at,
                status,
                sanitize_error(exc),
                failure_class=failure_class,
                failure_code=failure_code,
            )
        finally:
            if reader is not None:
                reader.close()
            elif owned_transport and transport is not None:
                transport.close()


def build_snapshot(state: CollectedState, *, captured_at: datetime) -> BrokerSnapshot:
    warnings: list[str] = []
    diagnostics = _diagnostics_from_state(state)
    status = _status_from_state(state, diagnostics=diagnostics)
    accounts = []
    for row in state.entities.get("ClientAccountEntity", {}).values():
        if account_has_undocumented_kind_fields(row):
            warnings.append("iis_classification_unresolved")
        account = normalize_account(row)
        if account is not None:
            accounts.append(account)
    subaccounts = [
        item
        for item in (
            normalize_subaccount(row)
            for row in state.entities.get("ClientSubAccountEntity", {}).values()
        )
        if item is not None
    ]
    sections = [
        item
        for item in (
            normalize_section(row)
            for row in state.entities.get("SubAccountRazdelEntity", {}).values()
        )
        if item is not None
    ]
    instruments = state.entities.get("AssetInfoEntity", {})
    positions = [
        item
        for item in (
            normalize_position(row, instruments=instruments)
            for row in state.entities.get("ClientPositionEntity", {}).values()
        )
        if item is not None
    ]
    cash = [
        item
        for item in (
            normalize_cash(row) for row in state.entities.get("ClientBalanceEntity", {}).values()
        )
        if item is not None
    ]
    if any(position.market_value is None for position in positions):
        warnings.append("position_market_value_not_documented")
    query_status = tuple(
        f"{name}={state.query_status.get(name, 'unresolved')}"
        for name in (*REQUIRED_SNAPSHOT_ENTITIES, "AssetInfoEntity")
        if name in state.query_status or name in REQUIRED_SNAPSHOT_ENTITIES
    )
    provenance = SnapshotProvenance(
        provider=ALFA_PRO_PROVIDER,
        api_doc_version=API_DOC_VERSION,
        captured_at=captured_at,
        timestamp_provenance=TimestampProvenance.LOCAL_OBSERVATION,
        auth_status=state.auth_status,
        ready_to_sign=state.ready_to_sign,
        channels_invoked=tuple(state.channels_invoked),
        entity_query_status=query_status,
        eligible_for_apply=status is SnapshotStatus.COMPLETE,
        compatibility_state=diagnostics.compatibility_state,
        compatibility_fingerprint=diagnostics.compatibility_fingerprint,
        failure_class=diagnostics.failure_class,
    )
    diagnostics = diagnostics.with_snapshot(
        status=status.value,
        eligible_for_apply=status is SnapshotStatus.COMPLETE,
    )
    source_as_of = captured_at if status is SnapshotStatus.COMPLETE else captured_at
    return BrokerSnapshot(
        provider=ALFA_PRO_PROVIDER,
        status=status,
        source_as_of=source_as_of,
        accounts=tuple(accounts),
        subaccounts=tuple(subaccounts),
        sections=tuple(sections),
        positions=tuple(positions),
        cash_balances=tuple(cash),
        warnings=tuple(dict.fromkeys(warnings)),
        provenance=provenance,
        message=_status_message(status),
        diagnostics=diagnostics,
    )


def sanitize_error(exc: BaseException) -> str:
    name = type(exc).__name__
    if name == "ForbiddenAlfaChannel":
        return f"{name}: order/trading channel denied"
    if name in {"TimeoutError", "Timeout"}:
        return f"{name}: bounded wait elapsed"
    if name in {"OSError", "ConnectionRefusedError", "ConnectionResetError"}:
        return f"{name}: connection failed"
    if name in {"InvalidHandshake", "InvalidStatus", "InvalidStatusCode", "InvalidHeader"}:
        return f"{name}: websocket handshake rejected"
    if name == "AlfaSnapshotEndpointError":
        return f"{name}: invalid endpoint"
    if name == "AlfaSnapshotTimeoutError":
        return f"{name}: timeout outside bounds"
    return f"{name}: snapshot failed"


def _diagnostics_from_state(state: CollectedState) -> AlfaDiagnosticReport:
    evaluation = evaluate_compatibility(
        api_doc_version=API_DOC_VERSION,
        observed_alfa_pro_version=state.observed_alfa_pro_version,
        observed_api_version=state.observed_api_version,
        observed_protocol_version=state.observed_protocol_version,
        message_shapes=state.observed_message_shapes,
        entity_payload_fields=state.entity_payload_fields,
        entity_fields=state.entity_fields,
        protocol_anomalies=state.protocol_anomalies,
        layout_anomalies=state.layout_anomalies,
    )
    entity_status = tuple(
        f"{name}={state.query_status[name]}" for name in sorted(state.query_status)
    )
    entity_counts = tuple(
        f"{name}={len(state.entities.get(name, {}))}" for name in sorted(state.entities)
    )
    observed_fields = tuple(
        f"{name}={{{','.join(safe_field_names(fields))}}}"
        for name, fields in sorted(state.entity_fields.items())
    )
    diagnostics = diagnostic_from_evaluation(
        evaluation,
        api_doc_version=API_DOC_VERSION,
        entity_status=entity_status,
        entity_counts=entity_counts,
        observed_fields=observed_fields,
    )
    if state.transport_error:
        return diagnostics.with_failure(
            AlfaDiagnosticFailureClass.CONNECTION, "transport_read_failed"
        )
    if state.routing_error:
        return diagnostics.with_failure(AlfaDiagnosticFailureClass.ROUTING, "router_error")
    if state.error_codes:
        return diagnostics.with_failure(AlfaDiagnosticFailureClass.ROUTING, "entity_query_failed")
    if state.protocol_anomalies:
        return diagnostics.with_failure(
            AlfaDiagnosticFailureClass.PROTOCOL, *sorted(state.protocol_anomalies)
        )
    if state.layout_anomalies or state.malformed:
        return diagnostics.with_failure(
            AlfaDiagnosticFailureClass.LAYOUT,
            *(sorted(state.layout_anomalies) or ("malformed_response",)),
        )
    if state.auth_status is None:
        return diagnostics.with_failure(AlfaDiagnosticFailureClass.AUTH, "auth_unresolved")
    if state.lost_auth:
        return diagnostics.with_failure(AlfaDiagnosticFailureClass.AUTH, "auth_lost")
    if state.auth_status != 2:
        return diagnostics.with_failure(AlfaDiagnosticFailureClass.AUTH, "auth_not_authorized")
    if state.truncated or state.entity_truncated:
        return diagnostics.with_failure(AlfaDiagnosticFailureClass.PROTOCOL, "collection_truncated")
    if not asset_info_batches_complete(state):
        return diagnostics.with_failure(
            AlfaDiagnosticFailureClass.PROTOCOL, "asset_info_incomplete"
        )
    return diagnostics


def _status_from_state(
    state: CollectedState,
    *,
    diagnostics: AlfaDiagnosticReport,
) -> SnapshotStatus:
    if state.transport_error:
        return SnapshotStatus.PROVIDER_UNAVAILABLE
    if state.malformed:
        return SnapshotStatus.MALFORMED_RESPONSE
    if state.lost_auth:
        return SnapshotStatus.INCOMPLETE
    if state.auth_status is None:
        if state.routing_error:
            return SnapshotStatus.COMPATIBILITY_ERROR
        return SnapshotStatus.AUTH_UNRESOLVED
    if state.auth_status != 2:
        return SnapshotStatus.AUTH_NOT_AUTHORIZED
    if state.truncated or state.entity_truncated:
        return SnapshotStatus.INCOMPLETE
    if positions_missing_instrument_ref(state):
        return SnapshotStatus.MALFORMED_RESPONSE
    for name in REQUIRED_SNAPSHOT_ENTITIES:
        status = state.query_status.get(name)
        if status != "ok":
            return SnapshotStatus.INCOMPLETE
    if not asset_info_batches_complete(state):
        return SnapshotStatus.INCOMPLETE
    if diagnostics.compatibility_state is not AlfaCompatibilityState.COMPATIBLE:
        return SnapshotStatus.COMPATIBILITY_ERROR
    return SnapshotStatus.COMPLETE


def _status_message(status: SnapshotStatus) -> str:
    return f"snapshot_status={status.value}"


def _empty_snapshot(
    captured_at: datetime,
    status: SnapshotStatus,
    message: str,
    *,
    failure_class: AlfaDiagnosticFailureClass,
    failure_code: str,
) -> BrokerSnapshot:
    diagnostics = diagnostic_for_failure(
        api_doc_version=API_DOC_VERSION,
        failure_class=failure_class,
        failure_code=failure_code,
        snapshot_status=status.value,
    )
    return BrokerSnapshot(
        provider=ALFA_PRO_PROVIDER,
        status=status,
        source_as_of=captured_at,
        accounts=(),
        subaccounts=(),
        sections=(),
        positions=(),
        cash_balances=(),
        warnings=(),
        provenance=SnapshotProvenance(
            provider=ALFA_PRO_PROVIDER,
            api_doc_version=API_DOC_VERSION,
            captured_at=captured_at,
            timestamp_provenance=TimestampProvenance.LOCAL_OBSERVATION,
            auth_status=None,
            ready_to_sign=None,
            channels_invoked=(),
            entity_query_status=(),
            eligible_for_apply=False,
            compatibility_state=diagnostics.compatibility_state,
            compatibility_fingerprint=diagnostics.compatibility_fingerprint,
            failure_class=diagnostics.failure_class,
        ),
        message=message,
        diagnostics=diagnostics,
    )
