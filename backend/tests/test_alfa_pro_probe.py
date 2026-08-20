"""R06-01: bounded Alfa PRO read-only probe, synthetic/mocked only."""

from __future__ import annotations

import importlib
import json
import socket
import sys
import time
from pathlib import Path

import pytest

from hermes_finance.alfa_pro_probe.channels import (
    ALLOWED_BUS_CHANNELS,
    ALLOWED_ENTITY_TYPES,
    ALLOWED_REQUEST_CHANNELS,
    ForbiddenAlfaChannel,
    assert_router_send_allowed,
)
from hermes_finance.alfa_pro_probe.cli import main
from hermes_finance.alfa_pro_probe.protocol import (
    AlfaProbeEndpointError,
    encode_router_message,
    validate_endpoint,
)
from hermes_finance.alfa_pro_probe.reader import (
    AlfaProReadonlyReader,
    run_bus_gated_client_session,
    run_connection_state_bus_session,
    run_readonly_session,
)
from hermes_finance.alfa_pro_probe.report import build_report

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "alfa_pro" / "synthetic_read_only.json"
)
PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "hermes_finance" / "alfa_pro_probe"
ORDER_CHANNEL_LITERALS = (
    "#Order.Enter.Query",
    "#Order.Cancel.Query",
    "#Order.Limit.Query",
)


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class ScriptedTransport:
    def __init__(self, fixture: dict[str, object]) -> None:
        self.fixture = fixture
        self.sent: list[str] = []
        self.closed = False
        self._queue: list[str] = []

    def send_text(self, message: str) -> None:
        self.sent.append(message)
        parsed = json.loads(message)
        command = parsed.get("Command")
        channel = parsed.get("Channel")
        request_id = parsed.get("Id")
        raw_payload = parsed.get("Payload")
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else {}
        if command == "listen" and channel == "#ConnectionState.Bus":
            if self.fixture.get("emit_connection_state_bus", True):
                self._queue.append(
                    encode_router_message(
                        "broadcast",
                        "#ConnectionState.Bus",
                        payload=self.fixture["connection_state"],
                    )
                )
        if command != "request":
            return
        entity = payload.get("Type") if isinstance(payload, dict) else None
        if entity == "ConnectionState":
            typed_error = self.fixture.get("typed_connection_state_error")
            if isinstance(typed_error, int):
                self._queue.append(
                    encode_router_message(
                        "response",
                        "#Data.Query",
                        payload={
                            "Type": "ConnectionState",
                            "Error": {"Code": typed_error, "Message": "secret provider fail"},
                        },
                        request_id=str(request_id) if request_id else None,
                    )
                )
                return
            self._queue.append(
                encode_router_message(
                    "response",
                    "#Data.Query",
                    payload=self.fixture["connection_state"],
                    request_id=str(request_id) if request_id else None,
                )
            )
            return
        if isinstance(entity, str):
            errors = self.fixture.get("errors")
            if isinstance(errors, dict) and entity in errors:
                self._queue.append(
                    encode_router_message(
                        "response",
                        "#Data.Query",
                        payload={
                            "Type": entity,
                            "Error": {"Code": errors[entity], "Message": "secret provider fail"},
                        },
                        request_id=str(request_id) if request_id else None,
                    )
                )
                return
            rows = self.fixture.get(entity, [])
            self._queue.append(
                encode_router_message(
                    "response",
                    "#Data.Query",
                    payload={"Type": entity, "Data": rows},
                    request_id=str(request_id) if request_id else None,
                )
            )
            return
        documented_error = self.fixture.get("connection_state_error")
        if isinstance(documented_error, int):
            self._queue.append(
                encode_router_message(
                    "response",
                    "#Data.Query",
                    payload={
                        "Error": {"Code": documented_error, "Message": "secret provider fail"},
                    },
                    request_id=str(request_id) if request_id else None,
                )
            )
            return
        self._queue.append(
            encode_router_message(
                "response",
                "#Data.Query",
                payload=self.fixture["connection_state"],
                request_id=str(request_id) if request_id else None,
            )
        )

    def recv_text(self, timeout: float) -> str:
        if not self._queue:
            raise TimeoutError
        return self._queue.pop(0)

    def close(self) -> None:
        self.closed = True


class EmptyTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    def send_text(self, message: str) -> None:
        self.sent.append(message)

    def recv_text(self, timeout: float) -> str:
        raise TimeoutError

    def close(self) -> None:
        self.closed = True


def test_probe_refuses_without_live() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_import_and_helpers_do_not_open_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    module = importlib.reload(importlib.import_module("hermes_finance.alfa_pro_probe"))
    validate_endpoint(module.DEFAULT_ENDPOINT)
    assert "hermes_finance.alfa_pro_probe.live" not in sys.modules


def test_loopback_only_endpoint() -> None:
    assert validate_endpoint("ws://127.0.0.1:3366/router/") == "ws://127.0.0.1:3366/router/"
    assert validate_endpoint("ws://localhost:3366/router/").startswith("ws://localhost:3366")
    with pytest.raises(AlfaProbeEndpointError):
        validate_endpoint("ws://10.0.0.1:3366/router/")
    with pytest.raises(AlfaProbeEndpointError):
        validate_endpoint("ws://192.168.1.10:3366/router/")
    with pytest.raises(AlfaProbeEndpointError):
        validate_endpoint("wss://127.0.0.1:3366/router/")
    with pytest.raises(AlfaProbeEndpointError):
        validate_endpoint("ws://example.com:3366/router/")
    with pytest.raises(AlfaProbeEndpointError):
        validate_endpoint("ws://user:pass@127.0.0.1:3366/router/")


def test_non_loopback_live_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("connected")

    monkeypatch.setattr("hermes_finance.alfa_pro_probe.live.open_websocket", boom)
    monkeypatch.setattr("hermes_finance.alfa_pro_probe.live.run_live", boom)
    code = main(["--live", "--endpoint", "ws://8.8.8.8:3366/router/"])
    assert code == 2


def test_allowlist_is_read_only() -> None:
    assert "#Data.Query" in ALLOWED_REQUEST_CHANNELS
    assert "#ConnectionState.Bus" in ALLOWED_BUS_CHANNELS
    assert "ClientAccountEntity" in ALLOWED_ENTITY_TYPES
    assert "ClientPositionEntity" in ALLOWED_ENTITY_TYPES
    assert "ClientOperationEntity" in ALLOWED_ENTITY_TYPES
    for channel in ALLOWED_BUS_CHANNELS | ALLOWED_REQUEST_CHANNELS:
        assert not channel.casefold().startswith("#order.")
    for entity in ALLOWED_ENTITY_TYPES:
        assert not entity.startswith("Order")


def test_hard_deny_order_channels() -> None:
    transport = EmptyTransport()
    reader = AlfaProReadonlyReader(transport)
    for channel in ORDER_CHANNEL_LITERALS:
        with pytest.raises(ForbiddenAlfaChannel, match="trading channel"):
            assert_router_send_allowed("request", channel)
        with pytest.raises(ForbiddenAlfaChannel, match="trading channel"):
            reader._dispatch("request", channel, payload={"BuySell": 1})
    with pytest.raises(ForbiddenAlfaChannel):
        reader.subscribe_entity("OrderEntity")
    with pytest.raises(ForbiddenAlfaChannel):
        reader._dispatch("broadcast", "#ConnectionState.Bus")
    with pytest.raises(ForbiddenAlfaChannel):
        reader._dispatch("register", "#Data.Query")
    assert not hasattr(AlfaProReadonlyReader, "send")
    assert not any("#Order." in item for item in transport.sent)


def test_source_has_no_order_channel_literals() -> None:
    for path in PACKAGE_ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for literal in ORDER_CHANNEL_LITERALS:
            assert literal not in text, f"{path.name} contains {literal}"


def test_bounded_timeout_does_not_hang() -> None:
    reader = AlfaProReadonlyReader(EmptyTransport(), read_timeout=0.05)
    run_readonly_session(reader, deadline=time.monotonic() + 0.2)
    assert reader.state.messages_seen == 0
    assert reader.state.auth_status is None


def test_sanitized_error_and_output_omit_private_values() -> None:
    from hermes_finance.alfa_pro_probe.report import sanitize_error

    class FakeFrame(Exception):
        def __str__(self) -> str:
            return 'Payload={"Login":"real.user","Money":12345.67}'

    text = sanitize_error(FakeFrame())
    assert "real.user" not in text
    assert "12345.67" not in text
    assert "Payload" not in text
    assert text.endswith("probe failed")


def test_probe_does_not_persist_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    transport = ScriptedTransport(load_fixture())
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    build_report(state, connection="pass")
    assert list(tmp_path.iterdir()) == []
    assert transport.closed is False
    reader.close()
    assert transport.closed is True


def test_synthetic_account_position_operation_parsing() -> None:
    fixture = load_fixture()
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    text = report.to_text()

    assert report.connection == "pass"
    assert report.authenticated_read == "pass"
    assert report.auth_status == "2"
    assert report.auth_status_source in {"query", "bus"}
    assert report.ready_to_sign_observed == "true"
    request_payloads = _request_payloads(transport.sent)
    assert request_payloads
    assert request_payloads[0] == {"Init": True, "Subscribe": True}
    assert all(item.get("Type") != "ConnectionState" for item in request_payloads)
    assert report.accounts_count == 1
    assert report.subaccounts_count == 2
    assert report.razdels_count == 1
    assert report.iis_explicitly_classifiable == "unresolved"
    assert report.subaccounts_with_account_ref == "2/2"
    assert report.razdels_with_account_ref == "1/1"
    assert report.razdels_with_subaccount_ref == "1/1"
    assert report.positions_count == 2
    assert report.positions_with_isin == "1/2"
    assert report.positions_with_account_ref == "2/2"
    assert report.positions_with_subaccount_ref == "2/2"
    assert report.positions_with_razdel_ref == "2/2"
    assert report.positions_with_object_ref == "2/2"
    assert report.cash_balance_entities_count == 1
    assert report.collection_truncated == "no"
    assert "ClientOperationEntity=ok" in report.entity_query
    assert report.snapshot_fields == [
        "quantity",
        "valuation",
        "accounting_price",
        "nkd",
        "unrealized",
    ]
    assert report.operations_count == 2
    assert report.oldest_operation_date == "2024-01-15"
    assert report.newest_operation_date == "2025-06-01"
    assert report.observed_operation_types == ["DIV", "TRD"]
    assert report.non_trade_ledger_events_observed == "yes"
    assert report.trading_methods_invoked == "no"
    assert report.raw_payload_saved == "no"
    assert "TorgPos=json_number" in report.value_encodings
    assert "Money=json_number" in report.value_encodings
    assert "listen:#ConnectionState.Bus" in report.channels_invoked
    assert "request:#Data.Query" in report.channels_invoked
    assert not any(
        item.casefold().startswith("request:#order.") for item in report.channels_invoked
    )

    assert "synth.user" not in text
    assert "Synthetic Owner" not in text
    assert "SYNTH" not in text
    assert "RU000SYNTH01" not in text
    assert "250.5" not in text
    assert "1500" not in text
    assert "id_fingerprints" not in text
    assert "secret provider fail" not in text
    assert any(item.startswith("ClientAccountEntity={") for item in report.observed_fields)


def test_iis_is_not_inferred_from_name_or_code() -> None:
    fixture = load_fixture()
    accounts = fixture["ClientAccountEntity"]
    assert isinstance(accounts, list)
    accounts[0]["Name"] = "IIS main"
    razdels = fixture["SubAccountRazdelEntity"]
    assert isinstance(razdels, list)
    razdels[0]["RCode"] = "IIS"
    accounts[0]["IsIis"] = True
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    assert report.iis_explicitly_classifiable == "unresolved"
    assert "IIS main" not in report.to_text()


def test_ready_to_sign_false_is_observation_only() -> None:
    fixture = load_fixture()
    connection = fixture["connection_state"]
    assert isinstance(connection, dict)
    states = connection["States"]
    assert isinstance(states, dict)
    sign = states["SignService"]
    assert isinstance(sign, dict)
    sign["ReadyToSign"] = False
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    assert report.ready_to_sign_observed == "false"
    assert report.authenticated_read == "pass"
    assert report.read_with_ready_to_sign_false == "pass"
    sent_payloads = " ".join(transport.sent)
    assert "ReadyToSign" not in sent_payloads
    assert not any("Order" in item for item in transport.sent)


def test_unauthenticated_state_skips_client_queries() -> None:
    fixture = load_fixture()
    connection = fixture["connection_state"]
    assert isinstance(connection, dict)
    states = connection["States"]
    assert isinstance(states, dict)
    user = states["User"]
    assert isinstance(user, dict)
    user["AuthStatus"] = 1
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    assert report.authenticated_read == "fail"
    assert report.auth_status == "1"
    assert report.accounts_count == 0
    joined = " ".join(transport.sent)
    assert "ClientAccountEntity" not in joined
    assert "ClientPositionEntity" not in joined
    assert all(item.get("Type") != "ConnectionState" for item in _request_payloads(transport.sent))


def test_no_legacy_broker_portfolio_provider_name() -> None:
    with pytest.raises(ImportError):
        importlib.import_module("hermes_finance.AlfaProBrokerPortfolioProvider")


def test_origin_handshake_sends_no_client_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    class HandshakeSocket:
        def send(self, message: str) -> None:
            sent.append(message)

        def recv(self, timeout: float = 0) -> str:
            raise AssertionError("handshake must not read client data")

        def close(self) -> None:
            return None

    def fake_open(endpoint: str, *, origin: str | None, open_timeout: float) -> object:
        assert origin == "https://example.invalid"
        assert "127.0.0.1" not in origin
        assert endpoint.startswith("ws://127.0.0.1:")
        from hermes_finance.alfa_pro_probe.live import WebsocketTransport

        return WebsocketTransport(HandshakeSocket())

    monkeypatch.setattr("hermes_finance.alfa_pro_probe.live.open_websocket", fake_open)
    from hermes_finance.alfa_pro_probe.live import LiveConfig, run_live

    report = run_live(
        LiveConfig(endpoint="ws://127.0.0.1:3366/router/", origin_handshake_only=True)
    )
    assert report.foreign_origin_websocket_handshake == "accepted"
    assert report.connection == "pass"
    assert sent == []
    assert report.trading_methods_invoked == "no"


def test_official_fixture_has_no_owner_payload() -> None:
    dumped = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "t." not in dumped
    assert "Bearer" not in dumped
    assert "Authorization" not in dumped
    assert "finance.db" not in dumped
    fixture = load_fixture()
    assert fixture["meta"]["source"].startswith("synthetic")
    account = fixture["ClientAccountEntity"][0]
    assert account == {"IdAccount": 101}


def test_provider_error_does_not_look_like_empty_complete_history() -> None:
    fixture = load_fixture()
    fixture["errors"] = {"ClientOperationEntity": 5}
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    text = report.to_text()
    assert report.operations_count == 0
    assert "ClientOperationEntity=error" in report.entity_query
    assert "ClientOperationEntity=5" in report.entity_error_codes
    assert report.oldest_operation_date == "unresolved"
    assert report.newest_operation_date == "unresolved"
    assert report.observed_operation_types == []
    assert report.non_trade_ledger_events_observed == "unresolved"
    assert "secret provider fail" not in text
    assert "Message" not in text


def test_truncated_operations_mark_history_unresolved() -> None:
    fixture = load_fixture()
    fixture["ClientOperationEntity"] = [
        {
            "IdOperation": 800 + index,
            "TimeOperation": "2023-01-01T00:00:00Z",
            "IdOperationType": "TRD",
            "IdObject": 501,
            "Quantity": 1,
            "IdAccount": 101,
        }
        for index in range(6)
    ]
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport, max_operation_rows=2)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    assert report.collection_truncated == "yes"
    assert "ClientOperationEntity" in report.entity_truncated
    assert report.operations_count == 2
    assert report.oldest_operation_date == "unresolved"
    assert report.newest_operation_date == "unresolved"
    assert report.non_trade_ledger_events_observed == "unresolved"
    assert "2023-01-01" not in report.to_text()


def test_default_stdout_has_no_raw_ids_or_id_digests() -> None:
    import hashlib

    transport = ScriptedTransport(load_fixture())
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    text = build_report(state, connection="pass").to_text()
    digest = hashlib.sha256(b"101").hexdigest()
    assert "id_fingerprints" not in text
    assert digest not in text
    assert digest[:16] not in text
    assert "\n101\n" not in text
    assert "IdAccount=101" not in text


def test_handshake_rejects_loopback_origin() -> None:
    from hermes_finance.alfa_pro_probe.protocol import validate_handshake_origin

    with pytest.raises(AlfaProbeEndpointError):
        validate_handshake_origin("http://127.0.0.1:9")
    with pytest.raises(AlfaProbeEndpointError):
        validate_handshake_origin("http://localhost:9")
    assert validate_handshake_origin("https://example.invalid") == "https://example.invalid"
    code = main(["--live", "--origin-handshake-only", "--origin", "http://127.0.0.1:9"])
    assert code == 2


def test_owner_id_compare_store_emits_labels_only(tmp_path: Path) -> None:
    from hermes_finance.alfa_pro_probe.report import compare_id_sets
    from hermes_finance.settings import REPOSITORY_ROOT

    store = tmp_path / "id-compare.json"
    transport = ScriptedTransport(load_fixture())
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    first = build_report(state, connection="pass", id_compare_store=store)
    assert first.ids_after_restart_accounts == "unresolved"
    assert "id_fingerprints" not in first.to_text()
    stored = store.read_text(encoding="utf-8")
    assert '"101"' not in stored
    second = build_report(state, connection="pass", id_compare_store=store)
    assert second.ids_after_restart_accounts == "stable"
    state.entities["ClientAccountEntity"]["999"] = {"IdAccount": 999}
    mixed = build_report(state, connection="pass", id_compare_store=store)
    assert mixed.ids_after_restart_accounts == "mixed"
    leaked = REPOSITORY_ROOT / "backend" / "r06-01-id-store.json"
    with pytest.raises(ValueError, match="outside the repository"):
        compare_id_sets(
            leaked,
            {
                "accounts": ["1"],
                "subaccounts": [],
                "instruments": [],
                "operations": [],
            },
        )
    assert not leaked.exists()


class QueueTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self._queue: list[str] = []
        self.closed = False

    def send_text(self, message: str) -> None:
        self.sent.append(message)

    def recv_text(self, timeout: float) -> str:
        if not self._queue:
            raise TimeoutError
        return self._queue.pop(0)

    def close(self) -> None:
        self.closed = True

    def last_id(self) -> str:
        return str(json.loads(self.sent[-1])["Id"])


def _operation_row(operation_id: int, when: str) -> dict[str, object]:
    return {
        "IdOperation": operation_id,
        "TimeOperation": when,
        "IdOperationType": "TRD",
        "IdObject": 501,
        "Quantity": 1,
        "IdAccount": 101,
    }


def test_uncorrelated_routing_error_surfaces_code_not_message() -> None:
    transport = QueueTransport()
    reader = AlfaProReadonlyReader(transport)
    reader.subscribe_entity("ClientOperationEntity")
    transport._queue.append(json.dumps({"Code": 5, "Message": "secret router fail"}))
    reader.drain(time.monotonic() + 1)
    report = build_report(reader.state, connection="pass")
    text = report.to_text()
    assert report.routing_error == "yes"
    assert report.routing_error_code == "5"
    assert reader.state.query_status.get("ClientOperationEntity") == "unresolved"
    assert report.oldest_operation_date == "unresolved"
    assert report.newest_operation_date == "unresolved"
    assert "secret router fail" not in text
    assert "Message" not in text


def test_operation_bus_without_init_response_is_not_ok() -> None:
    transport = QueueTransport()
    reader = AlfaProReadonlyReader(transport)
    reader.listen_entity("ClientOperationEntity")
    reader.subscribe_entity("ClientOperationEntity")
    transport._queue.append(
        encode_router_message(
            "broadcast",
            "#Data.Bus.ClientOperationEntity",
            payload={
                "Type": "ClientOperationEntity",
                "Updated": [_operation_row(1, "2024-01-15T00:00:00Z")],
            },
        )
    )
    reader.drain(time.monotonic() + 1)
    report = build_report(reader.state, connection="pass")
    assert reader.state.query_status.get("ClientOperationEntity") == "unresolved"
    assert report.operations_count == 1
    assert "ClientOperationEntity=ok" not in report.entity_query
    assert report.oldest_operation_date == "unresolved"
    assert report.newest_operation_date == "unresolved"
    assert "2024-01-15" not in report.to_text()


def test_bus_then_routing_error_keeps_history_unresolved() -> None:
    transport = QueueTransport()
    reader = AlfaProReadonlyReader(transport)
    reader.subscribe_entity("ClientOperationEntity")
    transport._queue.extend(
        [
            encode_router_message(
                "response",
                "#Data.Query",
                payload={
                    "Type": "ClientOperationEntity",
                    "Data": [_operation_row(1, "2024-01-15T00:00:00Z")],
                },
                request_id=transport.last_id(),
            ),
            encode_router_message(
                "broadcast",
                "#Data.Bus.ClientOperationEntity",
                payload={
                    "Type": "ClientOperationEntity",
                    "Updated": [_operation_row(2, "2025-06-01T00:00:00Z")],
                },
            ),
            json.dumps({"Code": 5, "Message": "secret router fail"}),
        ]
    )
    reader.drain(time.monotonic() + 1)
    report = build_report(reader.state, connection="pass")
    assert reader.state.query_status.get("ClientOperationEntity") == "ok"
    assert report.routing_error == "yes"
    assert report.routing_error_code == "5"
    assert report.operations_count == 2
    assert report.oldest_operation_date == "unresolved"
    assert report.newest_operation_date == "unresolved"
    text = report.to_text()
    assert "secret router fail" not in text
    assert "2024-01-15" not in text
    assert "2025-06-01" not in text


def _request_payloads(sent: list[str]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for item in sent:
        parsed = json.loads(item)
        if parsed.get("Command") != "request":
            continue
        raw = parsed.get("Payload")
        payload = json.loads(raw) if isinstance(raw, str) else {}
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def test_documented_connection_state_error_without_auth_is_unresolved() -> None:
    fixture = load_fixture()
    fixture["emit_connection_state_bus"] = False
    fixture["connection_state_error"] = 6
    fixture["typed_connection_state_error"] = 6
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    text = report.to_text()
    assert report.connection == "pass"
    assert report.authenticated_read == "unresolved"
    assert report.auth_status == "unresolved"
    assert report.auth_status_source == "unresolved"
    assert report.accounts_count == 0
    assert "ConnectionState=error" in report.entity_query
    assert "ConnectionStateTyped=error" in report.entity_query
    assert "ConnectionState=6" in report.entity_error_codes
    assert "ConnectionStateTyped=6" in report.entity_error_codes
    assert "secret provider fail" not in text
    assert "Message" not in text
    joined = " ".join(transport.sent)
    assert "ClientAccountEntity" not in joined
    assert "ClientPositionEntity" not in joined
    assert "ClientOperationEntity" not in joined
    payloads = _request_payloads(transport.sent)
    assert payloads[0] == {"Init": True, "Subscribe": True}
    assert payloads[1] == {"Type": "ConnectionState", "Init": True, "Subscribe": True}


def test_connection_state_query_error_still_accepts_bus_authstatus() -> None:
    fixture = load_fixture()
    fixture["connection_state_error"] = 6
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    assert report.authenticated_read == "pass"
    assert report.auth_status == "2"
    assert report.auth_status_source == "bus"
    assert report.accounts_count == 1
    assert "ConnectionState=error" in report.entity_query
    assert "ConnectionState=6" in report.entity_error_codes
    assert all(item.get("Type") != "ConnectionState" for item in _request_payloads(transport.sent))


def test_typed_connection_state_fallback_after_documented_error() -> None:
    fixture = load_fixture()
    fixture["emit_connection_state_bus"] = False
    fixture["connection_state_error"] = 6
    transport = ScriptedTransport(fixture)
    reader = AlfaProReadonlyReader(transport)
    state = run_readonly_session(reader, deadline=time.monotonic() + 2)
    report = build_report(state, connection="pass")
    assert report.authenticated_read == "pass"
    assert report.auth_status == "2"
    assert report.auth_status_source == "query"
    assert report.accounts_count == 1
    assert "ConnectionState=error" in report.entity_query
    assert "ConnectionStateTyped=ok" in report.entity_query
    assert "ConnectionState=6" in report.entity_error_codes
    payloads = _request_payloads(transport.sent)
    assert payloads[0] == {"Init": True, "Subscribe": True}
    assert payloads[1] == {"Type": "ConnectionState", "Init": True, "Subscribe": True}
    assert any(item.get("Type") == "ClientAccountEntity" for item in payloads)


def test_connection_state_error_code_is_not_translated() -> None:
    fixture = load_fixture()
    fixture["emit_connection_state_bus"] = False
    fixture["connection_state_error"] = 6
    fixture["typed_connection_state_error"] = 6
    transport = ScriptedTransport(fixture)
    report = build_report(
        run_readonly_session(AlfaProReadonlyReader(transport), deadline=time.monotonic() + 2),
        connection="pass",
    )
    text = report.to_text().casefold()
    assert "connectionstate=6" in text.replace(" ", "")
    for banned in (
        "invalid type",
        "not authenticated",
        "unauthenticated",
        "unauthorized",
        "permission denied",
        "auth failed",
    ):
        assert banned not in text


class IdleThenBusTransport:
    def __init__(self, payload: object, *, idle_before_event: int) -> None:
        self.payload = payload
        self.idle_before_event = idle_before_event
        self.sent: list[str] = []
        self.recv_calls = 0
        self.closed = False
        self._emitted = False

    def send_text(self, message: str) -> None:
        self.sent.append(message)

    def recv_text(self, timeout: float) -> str:
        self.recv_calls += 1
        if not self._emitted and self.recv_calls > self.idle_before_event:
            self._emitted = True
            return encode_router_message(
                "broadcast",
                "#ConnectionState.Bus",
                payload=self.payload,
            )
        time.sleep(timeout)
        raise TimeoutError

    def close(self) -> None:
        self.closed = True


def _assert_bus_only_sends(sent: list[str]) -> None:
    commands = [str(json.loads(item).get("Command") or "") for item in sent]
    channels = [str(json.loads(item).get("Channel") or "") for item in sent]
    assert "request" not in commands
    assert "#Data.Query" not in channels
    assert all(channel == "#ConnectionState.Bus" for channel in channels)
    assert "listen" in commands


def test_bus_only_silence_across_read_timeouts_is_unresolved() -> None:
    transport = IdleThenBusTransport({}, idle_before_event=1000)
    reader = AlfaProReadonlyReader(transport, read_timeout=0.04)
    state = run_connection_state_bus_session(reader, deadline=time.monotonic() + 0.22)
    report = build_report(state, connection="pass")
    assert transport.recv_calls >= 3
    assert report.connection == "pass"
    assert report.authenticated_read == "unresolved"
    assert report.auth_status == "unresolved"
    assert report.auth_status_source == "unresolved"
    assert report.ready_to_sign_observed == "unresolved"
    assert report.probe_mode == "connection-state-bus-only"
    assert report.accounts_count == 0
    _assert_bus_only_sends(transport.sent)


def test_bus_only_delayed_event_after_read_timeouts() -> None:
    fixture = load_fixture()
    transport = IdleThenBusTransport(fixture["connection_state"], idle_before_event=2)
    reader = AlfaProReadonlyReader(transport, read_timeout=0.04)
    state = run_connection_state_bus_session(reader, deadline=time.monotonic() + 0.25)
    report = build_report(state, connection="pass")
    text = report.to_text()
    assert transport.recv_calls >= 3
    assert report.auth_status == "2"
    assert report.auth_status_source == "bus"
    assert report.ready_to_sign_observed == "true"
    assert report.authenticated_read == "unresolved"
    assert report.probe_mode == "connection-state-bus-only"
    assert report.accounts_count == 0
    assert "synth.user" not in text
    assert "Synthetic Owner" not in text
    _assert_bus_only_sends(transport.sent)
    payloads = _request_payloads(transport.sent)
    assert payloads == []


def test_bus_only_cli_rejects_handshake_combination() -> None:
    code = main(
        [
            "--live",
            "--connection-state-bus-only",
            "--origin-handshake-only",
        ]
    )
    assert code == 2


def test_bus_only_cli_uses_bus_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_live(config: object) -> object:
        captured["config"] = config
        from hermes_finance.alfa_pro_probe.report import ProbeReport

        return ProbeReport(connection="pass", probe_mode="connection-state-bus-only")

    monkeypatch.setattr("hermes_finance.alfa_pro_probe.live.run_live", fake_run_live)
    code = main(["--live", "--connection-state-bus-only"])
    assert code == 0
    config = captured["config"]
    assert getattr(config, "connection_state_bus_only") is True
    assert getattr(config, "origin_handshake_only") is False


class DelayedAuthScriptedTransport:
    def __init__(
        self,
        fixture: dict[str, object],
        *,
        idle_before_auth: int,
        emit_auth: bool = True,
        auth_status: int | None = 2,
    ) -> None:
        fixture = dict(fixture)
        fixture["emit_connection_state_bus"] = False
        connection = fixture.get("connection_state")
        if isinstance(connection, dict) and auth_status is not None:
            states = connection.get("States")
            if isinstance(states, dict):
                user = states.get("User")
                if isinstance(user, dict):
                    user["AuthStatus"] = auth_status
        self.inner = ScriptedTransport(fixture)
        self.idle_before_auth = idle_before_auth
        self.emit_auth = emit_auth
        self.recv_calls = 0
        self._auth_emitted = False

    @property
    def sent(self) -> list[str]:
        return self.inner.sent

    def send_text(self, message: str) -> None:
        self.inner.send_text(message)

    def recv_text(self, timeout: float) -> str:
        self.recv_calls += 1
        if self.inner._queue:
            return self.inner._queue.pop(0)
        if self.emit_auth and not self._auth_emitted and self.recv_calls > self.idle_before_auth:
            self._auth_emitted = True
            return encode_router_message(
                "broadcast",
                "#ConnectionState.Bus",
                payload=self.inner.fixture["connection_state"],
            )
        time.sleep(timeout)
        raise TimeoutError

    def close(self) -> None:
        self.inner.close()


def _has_connection_state_data_query(sent: list[str]) -> bool:
    for payload in _request_payloads(sent):
        entity = payload.get("Type")
        if entity == "ConnectionState" or entity is None:
            return True
    return False


def _client_query_types(sent: list[str]) -> list[str]:
    found: list[str] = []
    for payload in _request_payloads(sent):
        entity = payload.get("Type")
        if isinstance(entity, str) and entity != "ConnectionState":
            found.append(entity)
    return found


def test_bus_gated_delayed_auth_then_client_reads() -> None:
    transport = DelayedAuthScriptedTransport(load_fixture(), idle_before_auth=2)
    reader = AlfaProReadonlyReader(transport, read_timeout=0.04)
    state = run_bus_gated_client_session(reader, deadline=time.monotonic() + 0.3)
    report = build_report(state, connection="pass")
    text = report.to_text()
    assert transport.recv_calls >= 3
    assert report.auth_status == "2"
    assert report.auth_status_source == "bus"
    assert report.ready_to_sign_observed == "true"
    assert report.authenticated_read == "pass"
    assert report.probe_mode == "bus-gated-client-read"
    assert report.accounts_count == 1
    assert report.positions_count == 2
    assert not _has_connection_state_data_query(transport.sent)
    types = _client_query_types(transport.sent)
    assert types[0] == "ClientAccountEntity"
    assert "ClientPositionEntity" in types
    assert "ClientOperationEntity" in types
    assert "AssetInfoEntity" in types
    assert "ReadyToSign" not in " ".join(transport.sent)
    assert not any("#Order." in item for item in transport.sent)
    assert "synth.user" not in text
    assert "250.5" not in text
    assert "1500" not in text


def test_bus_gated_no_bus_state_sends_zero_client_queries() -> None:
    transport = DelayedAuthScriptedTransport(load_fixture(), idle_before_auth=2, emit_auth=False)
    reader = AlfaProReadonlyReader(transport, read_timeout=0.04)
    state = run_bus_gated_client_session(reader, deadline=time.monotonic() + 0.2)
    report = build_report(state, connection="pass")
    assert transport.recv_calls >= 3
    assert report.auth_status == "unresolved"
    assert report.authenticated_read == "unresolved"
    assert report.accounts_count == 0
    assert _client_query_types(transport.sent) == []
    assert not _has_connection_state_data_query(transport.sent)


def test_bus_gated_auth_not_2_sends_zero_client_queries() -> None:
    transport = DelayedAuthScriptedTransport(load_fixture(), idle_before_auth=1, auth_status=1)
    reader = AlfaProReadonlyReader(transport, read_timeout=0.04)
    state = run_bus_gated_client_session(reader, deadline=time.monotonic() + 0.2)
    report = build_report(state, connection="pass")
    assert report.auth_status == "1"
    assert report.auth_status_source == "bus"
    assert report.authenticated_read == "fail"
    assert report.accounts_count == 0
    assert _client_query_types(transport.sent) == []
    assert not _has_connection_state_data_query(transport.sent)


def test_bus_gated_cli_reaches_live_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_live(config: object) -> object:
        captured["config"] = config
        from hermes_finance.alfa_pro_probe.report import ProbeReport

        return ProbeReport(connection="pass", probe_mode="bus-gated-client-read")

    monkeypatch.setattr("hermes_finance.alfa_pro_probe.live.run_live", fake_run_live)
    code = main(["--live", "--bus-gated-client-read"])
    assert code == 0
    config = captured["config"]
    assert getattr(config, "bus_gated_client_read") is True
    assert getattr(config, "connection_state_bus_only") is False


def test_bus_gated_cli_rejects_bus_only_combination() -> None:
    code = main(["--live", "--bus-gated-client-read", "--connection-state-bus-only"])
    assert code == 2
