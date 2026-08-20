"""R06-03: production Alfa PRO snapshot adapter, synthetic/mocked only."""

from __future__ import annotations

import importlib
import json
import socket
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from hermes_finance.broker_data.alfa_pro.adapter import (
    AlfaProBrokerSnapshotProvider,
    sanitize_error,
)
from hermes_finance.broker_data.alfa_pro.channels import (
    ALLOWED_BUS_CHANNELS,
    ALLOWED_ENTITY_TYPES,
    ALLOWED_REQUEST_CHANNELS,
    REQUIRED_SNAPSHOT_ENTITIES,
    ForbiddenAlfaChannel,
    assert_router_send_allowed,
)
from hermes_finance.broker_data.alfa_pro.codec import (
    AlfaSnapshotEndpointError,
    decode_payload,
    encode_router_message,
    validate_endpoint,
)
from hermes_finance.broker_data.alfa_pro.mapping import as_decimal
from hermes_finance.broker_data.alfa_pro.reader import (
    MAX_ASSET_KEYS,
    MAX_CONNECT_TIMEOUT_S,
    MAX_READ_TIMEOUT_S,
    MAX_TOTAL_DEADLINE_S,
    AlfaProSnapshotReader,
    AlfaSnapshotTimeoutError,
    run_snapshot_session,
)
from hermes_finance.broker_data.dto import SnapshotStatus

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "alfa_pro" / "synthetic_snapshot.json"
PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "hermes_finance" / "broker_data"
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
        self._asset_info_batches = 0

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
        if not isinstance(entity, str):
            return
        kind = self.fixture.get("required_payload_kind")
        if isinstance(kind, str) and entity in REQUIRED_SNAPSHOT_ENTITIES:
            self._queue.append(_structurally_invalid_response(kind, request_id))
            return
        if entity == "AssetInfoEntity":
            self._asset_info_batches += 1
            silent_after = self.fixture.get("silent_asset_info_after")
            if isinstance(silent_after, int) and self._asset_info_batches > silent_after:
                return
            batch_errors = self.fixture.get("asset_info_batch_errors")
            if isinstance(batch_errors, dict) and self._asset_info_batches in batch_errors:
                self._queue.append(
                    encode_router_message(
                        "response",
                        "#Data.Query",
                        payload={
                            "Type": entity,
                            "Error": {
                                "Code": batch_errors[self._asset_info_batches],
                                "Message": "secret provider fail",
                            },
                        },
                        request_id=str(request_id) if request_id else None,
                    )
                )
                return
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
        if entity == "AssetInfoEntity" and isinstance(payload.get("Keys"), list):
            wanted = {key for key in payload["Keys"]}
            rows = [row for row in rows if isinstance(row, dict) and row.get("IdObject") in wanted]
        if entity == "AssetInfoEntity" and self.fixture.get("truncate_asset_info"):
            rows = list(rows) + [
                {"IdObject": 10_000 + index, "ISIN": f"RU000PAD{index:02d}"} for index in range(8)
            ]
        self._queue.append(
            encode_router_message(
                "response",
                "#Data.Query",
                payload={"Type": entity, "Data": rows},
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


class DelayedAuthScriptedTransport:
    def __init__(
        self,
        fixture: dict[str, object],
        *,
        idle_before_auth: int,
        emit_auth: bool = True,
        auth_status: int | None = 2,
        lose_auth_after: bool = False,
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
        self.lose_auth_after = lose_auth_after
        self.recv_calls = 0
        self._auth_emitted = False
        self._auth_lost = False

    @property
    def sent(self) -> list[str]:
        return self.inner.sent

    @property
    def closed(self) -> bool:
        return self.inner.closed

    def send_text(self, message: str) -> None:
        self.inner.send_text(message)

    def recv_text(self, timeout: float) -> str:
        self.recv_calls += 1
        if self.inner._queue:
            if (
                self.lose_auth_after
                and self._auth_emitted
                and not self._auth_lost
                and any("ClientAccountEntity" in item for item in self.inner.sent)
            ):
                self._auth_lost = True
                payload = json.loads(json.dumps(self.inner.fixture["connection_state"]))
                payload["States"]["User"]["AuthStatus"] = 1
                return encode_router_message(
                    "broadcast",
                    "#ConnectionState.Bus",
                    payload=payload,
                )
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


def _request_payloads(sent: list[str]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for raw in sent:
        message = json.loads(raw)
        if message.get("Command") != "request":
            continue
        payload = json.loads(message["Payload"]) if isinstance(message.get("Payload"), str) else {}
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _client_query_types(sent: list[str]) -> list[str]:
    found: list[str] = []
    for payload in _request_payloads(sent):
        entity = payload.get("Type")
        if isinstance(entity, str):
            found.append(entity)
    return found


def _structurally_invalid_response(kind: str, request_id: object) -> str:
    inner = {
        "null": "null",
        "array": "[]",
        "scalar": "1",
        "type_mismatch": json.dumps({"Type": "AssetInfoEntity", "Data": []}, separators=(",", ":")),
    }[kind]
    return json.dumps(
        {
            "Command": "response",
            "Channel": "#Data.Query",
            "Id": str(request_id) if request_id else None,
            "Payload": inner,
        },
        separators=(",", ":"),
    )


def _has_connection_state_data_query(sent: list[str]) -> bool:
    for payload in _request_payloads(sent):
        entity = payload.get("Type")
        if entity == "ConnectionState" or "Type" not in payload:
            return True
    return False


def test_import_opens_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    module = importlib.reload(importlib.import_module("hermes_finance.broker_data"))
    from hermes_finance.broker_data.alfa_pro import DEFAULT_ENDPOINT

    validate_endpoint(DEFAULT_ENDPOINT)
    assert module.ALFA_PRO_PROVIDER == "alfa_pro"


def test_loopback_only_endpoint() -> None:
    assert validate_endpoint("ws://127.0.0.1:3366/router/") == "ws://127.0.0.1:3366/router/"
    with pytest.raises(AlfaSnapshotEndpointError):
        validate_endpoint("ws://10.0.0.1:3366/router/")
    with pytest.raises(AlfaSnapshotEndpointError):
        validate_endpoint("wss://127.0.0.1:3366/router/")
    with pytest.raises(AlfaSnapshotEndpointError):
        AlfaProBrokerSnapshotProvider(endpoint="ws://8.8.8.8:3366/router/")


def test_bus_gated_delayed_auth_then_client_reads() -> None:
    transport = DelayedAuthScriptedTransport(load_fixture(), idle_before_auth=2)
    provider = AlfaProBrokerSnapshotProvider(
        transport=transport, read_timeout=0.04, total_deadline=0.4
    )
    snapshot = provider.fetch_snapshot()
    assert transport.recv_calls >= 3
    assert snapshot.status is SnapshotStatus.COMPLETE
    assert snapshot.provenance.auth_status == 2
    assert snapshot.provenance.ready_to_sign is True
    assert snapshot.provenance.eligible_for_apply is True
    assert snapshot.provenance.timestamp_provenance.value == "local_observation"
    assert snapshot.source_as_of is not None
    assert snapshot.source_as_of.tzinfo is not None
    assert not _has_connection_state_data_query(transport.sent)
    types = _client_query_types(transport.sent)
    assert types[0] == "ClientAccountEntity"
    assert list(REQUIRED_SNAPSHOT_ENTITIES) == types[:5]
    assert "AssetInfoEntity" in types
    assert "ReadyToSign" not in " ".join(transport.sent)
    assert not any("#Order." in item for item in transport.sent)
    assert transport.closed is True


def test_missing_auth_sends_zero_client_queries() -> None:
    transport = DelayedAuthScriptedTransport(load_fixture(), idle_before_auth=2, emit_auth=False)
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=transport, read_timeout=0.04, total_deadline=0.22
    ).fetch_snapshot()
    assert transport.recv_calls >= 3
    assert snapshot.status is SnapshotStatus.AUTH_UNRESOLVED
    assert snapshot.provenance.eligible_for_apply is False
    assert _client_query_types(transport.sent) == []
    assert not _has_connection_state_data_query(transport.sent)


def test_non_2_auth_sends_zero_client_queries() -> None:
    transport = DelayedAuthScriptedTransport(load_fixture(), idle_before_auth=1, auth_status=1)
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=transport, read_timeout=0.04, total_deadline=0.22
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.AUTH_NOT_AUTHORIZED
    assert snapshot.accounts == ()
    assert _client_query_types(transport.sent) == []
    assert not _has_connection_state_data_query(transport.sent)


def test_production_allowlist_excludes_history_and_orders() -> None:
    assert "ClientAccountEntity" in ALLOWED_ENTITY_TYPES
    assert all(name in ALLOWED_ENTITY_TYPES for name in REQUIRED_SNAPSHOT_ENTITIES)
    assert "#ConnectionState.Bus" in ALLOWED_BUS_CHANNELS
    assert ALLOWED_REQUEST_CHANNELS == frozenset({"#Data.Query"})
    for channel in ALLOWED_BUS_CHANNELS | ALLOWED_REQUEST_CHANNELS:
        assert not channel.casefold().startswith("#order.")
    for entity in ALLOWED_ENTITY_TYPES:
        assert not entity.startswith("Order")
        assert "Operation" not in entity


def test_hard_deny_order_and_unlisted_commands() -> None:
    transport = EmptyTransport()
    reader = AlfaProSnapshotReader(transport)
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
    with pytest.raises(ForbiddenAlfaChannel):
        reader.listen_entity("AllTradeEntity")
    assert not hasattr(AlfaProSnapshotReader, "send")
    assert not hasattr(AlfaProBrokerSnapshotProvider, "send")
    assert not any("#Order." in item for item in transport.sent)


def test_source_has_no_trading_or_history_literals() -> None:
    for path in PACKAGE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for literal in ORDER_CHANNEL_LITERALS:
            assert literal not in text, f"{path.name} contains {literal}"
        assert "ClientOperationEntity" not in text
        assert "fastapi" not in text.casefold()
        assert "sqlalchemy" not in text.casefold()
        assert "hermes_finance.persistence" not in text
        assert "hermes_finance.database" not in text
        assert "alfa_pro_probe" not in text


def test_json_numeric_tokens_use_decimal_not_float_roundtrip() -> None:
    token = "1.234567890123456789"
    raw = '{"Price": ' + token + "}"
    parsed = decode_payload(raw)
    assert isinstance(parsed, dict)
    assert parsed["Price"] == Decimal(token)
    float_round_trip = Decimal(str(json.loads(raw)["Price"]))
    assert parsed["Price"] != float_round_trip
    assert as_decimal(0.1) is None
    assert as_decimal(Decimal(token)) == Decimal(token)
    assert as_decimal(10) == Decimal(10)


def test_synthetic_happy_path_normalized_snapshot() -> None:
    transport = ScriptedTransport(load_fixture())
    snapshot = AlfaProBrokerSnapshotProvider(transport=transport, total_deadline=2).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.COMPLETE
    assert snapshot.provider == "alfa_pro"
    assert len(snapshot.accounts) == 1
    assert snapshot.accounts[0].provider_account_id == "101"
    assert len(snapshot.subaccounts) == 2
    assert len(snapshot.sections) == 1
    assert snapshot.sections[0].section_group == 1
    assert len(snapshot.positions) == 2
    equity = next(item for item in snapshot.positions if item.provider_instrument_id == "501")
    assert equity.quantity == Decimal(10)
    assert equity.broker_unit_price == Decimal("250.5")
    assert equity.accounting_price == Decimal("240")
    assert equity.accrued_interest_nkd == Decimal("1.25")
    assert equity.unrealized_result == Decimal("15.5")
    assert equity.market_value is None
    assert equity.isin == "RU000SYNTH01"
    assert equity.ticker == "SYNTH"
    assert "quantity=TorgPos" in equity.mapped_fields
    cash = snapshot.cash_balances[0]
    assert cash.amount == Decimal("1500.0")
    assert cash.currency == "RUB"
    assert snapshot.warnings == ("position_market_value_not_documented",)
    assert dataclasses_are_frozen(snapshot)
    text = " ".join(transport.sent)
    assert "secret provider fail" not in (snapshot.message or "")
    assert "synth.user" not in (snapshot.message or "")
    assert "RU000SYNTH01" not in (snapshot.message or "")
    assert "ReadyToSign" not in text


def dataclasses_are_frozen(snapshot: object) -> bool:
    from hermes_finance.broker_data.dto import BrokerSnapshot

    assert isinstance(snapshot, BrokerSnapshot)
    with pytest.raises(Exception):
        snapshot.status = SnapshotStatus.INCOMPLETE  # type: ignore[misc]
    return True


def test_required_entity_error_is_incomplete() -> None:
    fixture = load_fixture()
    fixture["errors"] = {"ClientPositionEntity": 5}
    transport = ScriptedTransport(fixture)
    snapshot = AlfaProBrokerSnapshotProvider(transport=transport, total_deadline=2).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.INCOMPLETE
    assert snapshot.provenance.eligible_for_apply is False
    assert "ClientPositionEntity=error" in snapshot.provenance.entity_query_status
    assert snapshot.message is not None
    assert "secret provider fail" not in snapshot.message


def test_truncation_is_incomplete() -> None:
    fixture = load_fixture()
    fixture["truncate_asset_info"] = True
    transport = ScriptedTransport(fixture)
    reader = AlfaProSnapshotReader(transport, max_rows=1)
    state = run_snapshot_session(reader, deadline=time.monotonic() + 2)
    from hermes_finance.broker_data.alfa_pro.adapter import build_snapshot

    snapshot = build_snapshot(state, captured_at=datetime.now(timezone.utc))
    assert snapshot.status is SnapshotStatus.INCOMPLETE
    assert snapshot.provenance.eligible_for_apply is False


def test_lost_auth_marks_incomplete() -> None:
    transport = DelayedAuthScriptedTransport(
        load_fixture(), idle_before_auth=0, lose_auth_after=True
    )
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=transport, read_timeout=0.04, total_deadline=0.4
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.INCOMPLETE
    assert snapshot.provenance.eligible_for_apply is False


def test_asset_info_request_uses_observed_position_object_ids() -> None:
    transport = ScriptedTransport(load_fixture())
    AlfaProBrokerSnapshotProvider(transport=transport, total_deadline=2).fetch_snapshot()
    asset_payloads = [
        payload
        for payload in _request_payloads(transport.sent)
        if payload.get("Type") == "AssetInfoEntity"
    ]
    assert len(asset_payloads) == 1
    keys = asset_payloads[0].get("Keys")
    assert keys == [501, 502]


def test_iis_is_not_inferred() -> None:
    fixture = load_fixture()
    accounts = fixture["ClientAccountEntity"]
    assert isinstance(accounts, list)
    accounts[0]["Name"] = "IIS main"
    accounts[0]["IIAType"] = 1
    razdels = fixture["SubAccountRazdelEntity"]
    assert isinstance(razdels, list)
    razdels[0]["RCode"] = "IIS"
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.accounts[0].provider_account_id == "101"
    assert not hasattr(snapshot.accounts[0], "iis")
    assert "iis_classification_unresolved" in snapshot.warnings
    assert snapshot.message is not None
    assert "IIS main" not in snapshot.message


def test_no_persistence_or_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    transport = ScriptedTransport(load_fixture())
    AlfaProBrokerSnapshotProvider(transport=transport, total_deadline=2).fetch_snapshot()
    assert list(tmp_path.iterdir()) == []
    assert transport.closed is True


def test_sanitized_errors_omit_private_values() -> None:
    class FakeFrame(Exception):
        def __str__(self) -> str:
            return 'Payload={"Login":"real.user","Money":12345.67}'

    text = sanitize_error(FakeFrame())
    assert "real.user" not in text
    assert "12345.67" not in text
    assert "Payload" not in text
    assert text.endswith("snapshot failed")


def test_provider_unavailable_on_connect_failure() -> None:
    def boom(endpoint: str, timeout: float) -> object:
        raise ConnectionRefusedError("terminal missing")

    snapshot = AlfaProBrokerSnapshotProvider(transport_factory=boom).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.PROVIDER_UNAVAILABLE
    assert snapshot.provenance.eligible_for_apply is False
    assert snapshot.message is not None
    assert "terminal missing" not in snapshot.message


def test_malformed_response_status() -> None:
    class JunkTransport:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.closed = False
            self._once = False

        def send_text(self, message: str) -> None:
            self.sent.append(message)

        def recv_text(self, timeout: float) -> str:
            if not self._once:
                self._once = True
                return "{not-json"
            raise TimeoutError

        def close(self) -> None:
            self.closed = True

    snapshot = AlfaProBrokerSnapshotProvider(
        transport=JunkTransport(), read_timeout=0.05, total_deadline=0.2
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.MALFORMED_RESPONSE
    assert snapshot.provenance.eligible_for_apply is False


def test_float_in_row_is_not_recovered() -> None:
    from hermes_finance.broker_data.alfa_pro.mapping import normalize_position

    row = {"IdPosition": 1, "IdObject": 9, "TorgPos": 0.1}
    position = normalize_position(row, instruments={})
    assert position is not None
    assert position.quantity is None


def test_mapping_table_does_not_accept_guesses() -> None:
    from hermes_finance.broker_data.alfa_pro.mapping import FIELD_MAPPINGS

    accepted = {
        (item.entity, item.alfa_field): item
        for item in FIELD_MAPPINGS
        if item.decision == "accepted"
    }
    unresolved = {
        (item.entity, item.alfa_field) for item in FIELD_MAPPINGS if item.decision == "unresolved"
    }
    assert ("ClientPositionEntity", "TorgPos") in accepted
    assert accepted[("ClientPositionEntity", "TorgPos")].snapshot_field == "quantity"
    assert ("ClientPositionEntity", "PSTNKD") in unresolved
    assert ("ClientPositionEntity", "DailyPL") in unresolved
    assert ("ClientBalanceEntity", "PortfolioCost") in unresolved
    assert all(
        item.snapshot_field is None for item in FIELD_MAPPINGS if item.decision != "accepted"
    )


def test_official_fixture_has_no_owner_payload() -> None:
    dumped = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "Bearer" not in dumped
    assert "finance.db" not in dumped
    fixture = load_fixture()
    assert str(fixture["meta"]["source"]).startswith("synthetic")
    assert fixture["ClientAccountEntity"] == [{"IdAccount": 101}]


def test_timeouts_reject_unbounded_and_non_finite_values() -> None:
    transport = EmptyTransport()
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(
            transport=transport, connect_timeout=MAX_CONNECT_TIMEOUT_S + 1
        )
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, read_timeout=MAX_READ_TIMEOUT_S + 1)
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, total_deadline=MAX_TOTAL_DEADLINE_S + 1)
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, connect_timeout=10**12)
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, read_timeout=0)
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, total_deadline=-1)
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, connect_timeout=float("inf"))
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, read_timeout=float("nan"))
    with pytest.raises(AlfaSnapshotTimeoutError):
        AlfaProBrokerSnapshotProvider(transport=transport, connect_timeout=True)
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(load_fixture())
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.COMPLETE


def _fixture_with_many_positions(count: int) -> dict[str, object]:
    fixture = load_fixture()
    fixture["ClientPositionEntity"] = [
        {
            "IdPosition": 2000 + index,
            "IdAccount": 101,
            "IdSubAccount": 201,
            "IdRazdel": 301,
            "IdObject": 8000 + index,
            "TorgPos": 1,
            "IsMoney": False,
        }
        for index in range(count)
    ]
    fixture["AssetInfoEntity"] = [
        {
            "IdObject": 8000 + index,
            "ISIN": f"RU000SYN{index:03d}",
            "Ticker": f"S{index:03d}",
            "Name": f"Synthetic {index}",
        }
        for index in range(count)
    ]
    return fixture


def test_asset_info_over_key_cap_cannot_be_complete_with_silent_loss() -> None:
    count = MAX_ASSET_KEYS + 1
    fixture = _fixture_with_many_positions(count)
    transport = ScriptedTransport(fixture)
    snapshot = AlfaProBrokerSnapshotProvider(transport=transport, total_deadline=2).fetch_snapshot()
    requested: set[int] = set()
    for payload in _request_payloads(transport.sent):
        if payload.get("Type") != "AssetInfoEntity":
            continue
        keys = payload.get("Keys")
        assert isinstance(keys, list)
        assert len(keys) <= MAX_ASSET_KEYS
        requested.update(int(key) for key in keys)
    expected = set(range(8000, 8000 + count))
    assert requested == expected
    if snapshot.status is SnapshotStatus.COMPLETE:
        assert len(snapshot.positions) == count
        assert all(item.isin for item in snapshot.positions)
        assert snapshot.provenance.eligible_for_apply is True
    else:
        assert snapshot.provenance.eligible_for_apply is False
        assert snapshot.status is SnapshotStatus.INCOMPLETE


def test_asset_info_second_batch_unresolved_is_never_complete() -> None:
    count = MAX_ASSET_KEYS + 1
    fixture = _fixture_with_many_positions(count)
    fixture["silent_asset_info_after"] = 1
    transport = ScriptedTransport(fixture)
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=transport, read_timeout=0.04, total_deadline=0.25
    ).fetch_snapshot()
    asset_requests = [
        payload
        for payload in _request_payloads(transport.sent)
        if payload.get("Type") == "AssetInfoEntity"
    ]
    assert len(asset_requests) == 2
    assert snapshot.status is SnapshotStatus.INCOMPLETE
    assert snapshot.provenance.eligible_for_apply is False
    assert snapshot.status is not SnapshotStatus.COMPLETE


def test_asset_info_second_batch_error_is_fail_closed() -> None:
    count = MAX_ASSET_KEYS + 1
    fixture = _fixture_with_many_positions(count)
    fixture["asset_info_batch_errors"] = {2: 5}
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.INCOMPLETE
    assert snapshot.provenance.eligible_for_apply is False
    assert snapshot.status is not SnapshotStatus.COMPLETE


def test_malformed_required_row_is_not_complete() -> None:
    fixture = load_fixture()
    positions = fixture["ClientPositionEntity"]
    assert isinstance(positions, list)
    positions.append({"TorgPos": 3, "Price": 10, "IdObject": 501})
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.MALFORMED_RESPONSE
    assert snapshot.provenance.eligible_for_apply is False


def test_malformed_required_account_row_is_not_complete() -> None:
    fixture = load_fixture()
    accounts = fixture["ClientAccountEntity"]
    assert isinstance(accounts, list)
    accounts.append({"Name": "brokerage"})
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.MALFORMED_RESPONSE
    assert snapshot.provenance.eligible_for_apply is False


@pytest.mark.parametrize("kind", ["null", "array", "scalar"])
def test_non_object_required_payloads_never_complete(kind: str) -> None:
    fixture = load_fixture()
    fixture["required_payload_kind"] = kind
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.MALFORMED_RESPONSE
    assert snapshot.provenance.eligible_for_apply is False
    assert snapshot.status is not SnapshotStatus.COMPLETE


def test_required_payload_type_mismatch_never_complete() -> None:
    fixture = load_fixture()
    fixture["required_payload_kind"] = "type_mismatch"
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.status is SnapshotStatus.MALFORMED_RESPONSE
    assert snapshot.provenance.eligible_for_apply is False
    assert snapshot.status is not SnapshotStatus.COMPLETE


def test_position_missing_idobject_never_complete() -> None:
    fixture = load_fixture()
    positions = fixture["ClientPositionEntity"]
    assert isinstance(positions, list)
    positions[0].pop("IdObject", None)
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.status in {SnapshotStatus.MALFORMED_RESPONSE, SnapshotStatus.INCOMPLETE}
    assert snapshot.provenance.eligible_for_apply is False
    assert snapshot.status is not SnapshotStatus.COMPLETE


def test_position_invalid_idobject_never_complete() -> None:
    fixture = load_fixture()
    positions = fixture["ClientPositionEntity"]
    assert isinstance(positions, list)
    positions[0]["IdObject"] = True
    snapshot = AlfaProBrokerSnapshotProvider(
        transport=ScriptedTransport(fixture), total_deadline=2
    ).fetch_snapshot()
    assert snapshot.status in {SnapshotStatus.MALFORMED_RESPONSE, SnapshotStatus.INCOMPLETE}
    assert snapshot.provenance.eligible_for_apply is False
    assert snapshot.status is not SnapshotStatus.COMPLETE
