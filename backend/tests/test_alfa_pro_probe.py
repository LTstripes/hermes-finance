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
        if isinstance(entity, str):
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
    assert report.ready_to_sign_observed == "true"
    assert report.accounts_count == 1
    assert report.subaccounts_count == 2
    assert report.iis_explicitly_classifiable == "unresolved"
    assert report.positions_count == 2
    assert report.positions_with_isin == "1/2"
    assert report.cash_balance_entities_count == 1
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
    assert "IdAccount" not in text


def test_iis_is_not_inferred_from_name_or_code() -> None:
    fixture = load_fixture()
    accounts = fixture["ClientAccountEntity"]
    assert isinstance(accounts, list)
    accounts[0]["Name"] = "IIS main"
    razdels = fixture["SubAccountRazdelEntity"]
    assert isinstance(razdels, list)
    razdels[0]["RCode"] = "IIS"
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
    assert report.accounts_count == 0
    joined = " ".join(transport.sent)
    assert "ClientAccountEntity" not in joined
    assert "ClientPositionEntity" not in joined


def test_no_broker_portfolio_provider_module() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hermes_finance.broker_data")
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
        assert origin == "http://127.0.0.1:9"
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
