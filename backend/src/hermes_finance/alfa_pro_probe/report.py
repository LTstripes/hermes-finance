"""Sanitized aggregate evidence. Counts, field names and labels only."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from hermes_finance.alfa_pro_probe.channels import API_DOC_VERSION, CLIENT_ENTITY_TYPES
from hermes_finance.alfa_pro_probe.reader import CollectedState
from hermes_finance.settings import REPOSITORY_ROOT

_SNAPSHOT_FIELDS = (
    ("quantity", ("TorgPos",)),
    ("valuation", ("Price", "PortfolioCost")),
    ("accounting_price", ("UchPrice",)),
    ("nkd", ("NKD", "PSTNKD")),
    ("unrealized", ("DailyPL", "NPL", "NPLtoMarketCurPrice")),
)
_SHAPE_FIELDS = (
    "TorgPos",
    "Price",
    "UchPrice",
    "NKD",
    "PSTNKD",
    "DailyPL",
    "NPL",
    "Money",
    "PortfolioCost",
    "Balance",
    "Quantity",
)
_ID_CLASSES = ("accounts", "subaccounts", "instruments", "operations")
_STATUS_ORDER = (
    "ConnectionState",
    *CLIENT_ENTITY_TYPES,
    "AssetInfoEntity",
)


@dataclass
class ProbeReport:
    alfa_pro_version: str = "unresolved"
    api_doc_version: str = API_DOC_VERSION
    connection: str = "unresolved"
    authenticated_read: str = "unresolved"
    ready_to_sign_observed: str = "unresolved"
    accounts_count: int = 0
    subaccounts_count: int = 0
    razdels_count: int = 0
    iis_explicitly_classifiable: str = "unresolved"
    subaccounts_with_account_ref: str = "0/0"
    razdels_with_account_ref: str = "0/0"
    razdels_with_subaccount_ref: str = "0/0"
    positions_count: int = 0
    positions_with_isin: str = "0/0"
    positions_with_account_ref: str = "0/0"
    positions_with_subaccount_ref: str = "0/0"
    positions_with_razdel_ref: str = "0/0"
    positions_with_object_ref: str = "0/0"
    cash_balance_entities_count: int = 0
    snapshot_fields: list[str] = field(default_factory=list)
    operations_count: int = 0
    oldest_operation_date: str = "unresolved"
    newest_operation_date: str = "unresolved"
    observed_operation_types: list[str] = field(default_factory=list)
    non_trade_ledger_events_observed: str = "unresolved"
    ids_after_restart_accounts: str = "unresolved"
    ids_after_restart_subaccounts: str = "unresolved"
    ids_after_restart_instruments: str = "unresolved"
    ids_after_restart_operations: str = "unresolved"
    read_with_ready_to_sign_false: str = "unresolved"
    foreign_origin_websocket_handshake: str = "unresolved"
    raw_payload_saved: str = "no"
    private_values_printed: str = "no"
    trading_methods_invoked: str = "no"
    collection_truncated: str = "no"
    entity_query: list[str] = field(default_factory=list)
    entity_truncated: list[str] = field(default_factory=list)
    entity_error_codes: list[str] = field(default_factory=list)
    observed_fields: list[str] = field(default_factory=list)
    value_encodings: list[str] = field(default_factory=list)
    channels_invoked: list[str] = field(default_factory=list)
    error: str = ""

    def to_text(self) -> str:
        snapshot = ", ".join(self.snapshot_fields) if self.snapshot_fields else ""
        types = ", ".join(self.observed_operation_types) if self.observed_operation_types else ""
        lines = [
            f"alfa_pro_version: {self.alfa_pro_version}",
            f"api_doc_version: {self.api_doc_version}",
            f"connection: {self.connection}",
            f"authenticated_read: {self.authenticated_read}",
            f"ready_to_sign_observed: {self.ready_to_sign_observed}",
            f"collection_truncated: {self.collection_truncated}",
            "",
            f"accounts_count: {self.accounts_count}",
            f"subaccounts_count: {self.subaccounts_count}",
            f"razdels_count: {self.razdels_count}",
            f"iis_explicitly_classifiable: {self.iis_explicitly_classifiable}",
            f"subaccounts_with_account_ref: {self.subaccounts_with_account_ref}",
            f"razdels_with_account_ref: {self.razdels_with_account_ref}",
            f"razdels_with_subaccount_ref: {self.razdels_with_subaccount_ref}",
            "",
            f"positions_count: {self.positions_count}",
            f"positions_with_isin: {self.positions_with_isin}",
            f"positions_with_account_ref: {self.positions_with_account_ref}",
            f"positions_with_subaccount_ref: {self.positions_with_subaccount_ref}",
            f"positions_with_razdel_ref: {self.positions_with_razdel_ref}",
            f"positions_with_object_ref: {self.positions_with_object_ref}",
            f"cash_balance_entities_count: {self.cash_balance_entities_count}",
            f"snapshot_fields: [{snapshot}]",
            "",
            f"operations_count: {self.operations_count}",
            f"oldest_operation_date: {self.oldest_operation_date}",
            f"newest_operation_date: {self.newest_operation_date}",
            f"observed_operation_types: [{types}]",
            f"non_trade_ledger_events_observed: {self.non_trade_ledger_events_observed}",
            "",
            "ids_after_restart:",
            f"  accounts: {self.ids_after_restart_accounts}",
            f"  subaccounts: {self.ids_after_restart_subaccounts}",
            f"  instruments: {self.ids_after_restart_instruments}",
            f"  operations: {self.ids_after_restart_operations}",
            "",
            f"read_with_ready_to_sign_false: {self.read_with_ready_to_sign_false}",
            f"foreign_origin_websocket_handshake: {self.foreign_origin_websocket_handshake}",
            "",
            f"raw_payload_saved: {self.raw_payload_saved}",
            f"private_values_printed: {self.private_values_printed}",
            f"trading_methods_invoked: {self.trading_methods_invoked}",
        ]
        if self.entity_query:
            lines.append("entity_query: [" + ", ".join(self.entity_query) + "]")
        if self.entity_truncated:
            lines.append("entity_truncated: [" + ", ".join(self.entity_truncated) + "]")
        if self.entity_error_codes:
            lines.append("entity_error_codes: [" + ", ".join(self.entity_error_codes) + "]")
        if self.observed_fields:
            lines.append("observed_fields: [" + ", ".join(self.observed_fields) + "]")
        if self.value_encodings:
            lines.append("value_encodings: [" + ", ".join(self.value_encodings) + "]")
        if self.channels_invoked:
            lines.append("channels_invoked: [" + ", ".join(self.channels_invoked) + "]")
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines) + "\n"


def build_report(
    state: CollectedState,
    *,
    connection: str,
    id_compare_store: Path | None = None,
) -> ProbeReport:
    accounts = state.entities.get("ClientAccountEntity", {})
    subaccounts = state.entities.get("ClientSubAccountEntity", {})
    razdels = state.entities.get("SubAccountRazdelEntity", {})
    positions = state.entities.get("ClientPositionEntity", {})
    balances = state.entities.get("ClientBalanceEntity", {})
    operations = state.entities.get("ClientOperationEntity", {})
    assets = state.entities.get("AssetInfoEntity", {})

    history_incomplete = _history_incomplete(state)
    types = _operation_types(operations)
    dates = [] if history_incomplete else _operation_dates(operations)

    report = ProbeReport(
        connection=connection,
        authenticated_read=_authenticated_read(state, connection),
        ready_to_sign_observed=_ready_label(state.ready_to_sign),
        collection_truncated=_yes_no(state.truncated or any(state.entity_truncated.values())),
        accounts_count=len(accounts),
        subaccounts_count=len(subaccounts),
        razdels_count=len(razdels),
        iis_explicitly_classifiable="unresolved",
        subaccounts_with_account_ref=_ref_count(subaccounts, "IdAccount"),
        razdels_with_account_ref=_ref_count(razdels, "IdAccount"),
        razdels_with_subaccount_ref=_ref_count(razdels, "IdSubAccount"),
        positions_count=len(positions),
        positions_with_isin=_isin_count(positions, assets),
        positions_with_account_ref=_ref_count(positions, "IdAccount"),
        positions_with_subaccount_ref=_ref_count(positions, "IdSubAccount"),
        positions_with_razdel_ref=_ref_count(positions, "IdRazdel"),
        positions_with_object_ref=_ref_count(positions, "IdObject"),
        cash_balance_entities_count=len(balances),
        snapshot_fields=_snapshot_fields(positions, balances),
        operations_count=len(operations),
        oldest_operation_date=dates[0] if dates else "unresolved",
        newest_operation_date=dates[-1] if dates else "unresolved",
        observed_operation_types=[] if history_incomplete else types,
        non_trade_ledger_events_observed=_non_trade(types, operations, history_incomplete),
        entity_query=_status_list(state),
        entity_truncated=sorted(name for name, flag in state.entity_truncated.items() if flag),
        entity_error_codes=[
            f"{name}={state.error_codes[name]}"
            for name in _STATUS_ORDER
            if name in state.error_codes
        ],
        observed_fields=_observed_fields(state),
        value_encodings=_value_encodings(positions, balances, operations),
        channels_invoked=list(state.channels_invoked),
        raw_payload_saved="no",
        private_values_printed="no",
        trading_methods_invoked="no",
    )
    if state.ready_to_sign is False and report.authenticated_read == "pass":
        report.read_with_ready_to_sign_false = "pass"
    if id_compare_store is not None:
        labels = compare_id_sets(
            id_compare_store, _id_sets(accounts, subaccounts, positions, assets, operations)
        )
        report.ids_after_restart_accounts = labels["accounts"]
        report.ids_after_restart_subaccounts = labels["subaccounts"]
        report.ids_after_restart_instruments = labels["instruments"]
        report.ids_after_restart_operations = labels["operations"]
    return report


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
    if name == "AlfaProbeEndpointError":
        return f"{name}: invalid endpoint or origin"
    return f"{name}: probe failed"


def compare_id_sets(store_path: Path, sets: dict[str, list[str]]) -> dict[str, str]:
    """Owner-only keyed comparison. Never prints the key or per-id digests."""

    path = store_path.expanduser().resolve()
    if _is_inside_repository(path):
        raise ValueError("id-compare store must be outside the repository")
    if path.exists():
        document = json.loads(path.read_text(encoding="utf-8"))
        key = bytes.fromhex(str(document["key"]))
        labels: dict[str, str] = {}
        for name in _ID_CLASSES:
            previous = set(document.get(name, []))
            current = set(_hmac_ids(key, sets.get(name, [])))
            labels[name] = _compare_label(previous, current)
        return labels
    key = os.urandom(32)
    document: dict[str, object] = {"key": key.hex()}
    for name in _ID_CLASSES:
        document[name] = _hmac_ids(key, sets.get(name, []))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return {name: "unresolved" for name in _ID_CLASSES}


def _is_inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        return False
    return True


def _hmac_ids(key: bytes, ids: list[str]) -> list[str]:
    return sorted(hmac.new(key, item.encode("utf-8"), "sha256").hexdigest() for item in ids)


def _compare_label(previous: set[str], current: set[str]) -> str:
    if previous == current:
        return "stable"
    if previous & current:
        return "mixed"
    return "changed"


def _id_sets(
    accounts: dict[str, dict[str, object]],
    subaccounts: dict[str, dict[str, object]],
    positions: dict[str, dict[str, object]],
    assets: dict[str, dict[str, object]],
    operations: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    instruments = set(positions) | set(assets)
    for row in positions.values():
        object_id = row.get("IdObject")
        if object_id is not None and not isinstance(object_id, bool):
            instruments.add(str(object_id))
    return {
        "accounts": sorted(accounts),
        "subaccounts": sorted(subaccounts),
        "instruments": sorted(instruments),
        "operations": sorted(operations),
    }


def _authenticated_read(state: CollectedState, connection: str) -> str:
    if connection != "pass":
        return "fail"
    if state.auth_status != 2:
        return "fail"
    client_ok = any(
        state.query_status.get(name) == "ok"
        for name in (
            "ClientAccountEntity",
            "ClientPositionEntity",
            "ClientBalanceEntity",
            "ClientOperationEntity",
        )
    )
    if client_ok:
        return "pass"
    has_client = any(
        state.entities.get(name)
        for name in (
            "ClientAccountEntity",
            "ClientPositionEntity",
            "ClientBalanceEntity",
            "ClientOperationEntity",
        )
    )
    return "pass" if has_client else "fail"


def _ready_label(value: bool | None) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unresolved"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _history_incomplete(state: CollectedState) -> bool:
    status = state.query_status.get("ClientOperationEntity", "unresolved")
    if status != "ok":
        return True
    return bool(state.entity_truncated.get("ClientOperationEntity"))


def _isin_count(
    positions: dict[str, dict[str, object]],
    assets: dict[str, dict[str, object]],
) -> str:
    present = _isin_presence(assets)
    with_isin = 0
    for row in positions.values():
        if str(row.get("IdObject")) in present:
            with_isin += 1
    return f"{with_isin}/{len(positions)}"


def _isin_presence(assets: dict[str, dict[str, object]]) -> set[str]:
    found: set[str] = set()
    for row in assets.values():
        object_id = row.get("IdObject")
        isin = row.get("ISIN")
        if object_id is None:
            continue
        if isinstance(isin, str) and isin.strip():
            found.add(str(object_id))
    return found


def _ref_count(rows: dict[str, dict[str, object]], key: str) -> str:
    if not rows:
        return "0/0"
    matched = sum(1 for row in rows.values() if _has_ref(row, key))
    return f"{matched}/{len(rows)}"


def _has_ref(row: dict[str, object], key: str) -> bool:
    if key not in row:
        return False
    value = row[key]
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _snapshot_fields(
    positions: dict[str, dict[str, object]],
    balances: dict[str, dict[str, object]],
) -> list[str]:
    present: list[str] = []
    rows = list(positions.values()) + list(balances.values())
    for label, keys in _SNAPSHOT_FIELDS:
        if any(any(key in row for key in keys) for row in rows):
            present.append(label)
    return present


def _operation_types(operations: dict[str, dict[str, object]]) -> list[str]:
    found: set[str] = set()
    for row in operations.values():
        raw = row.get("IdOperationType")
        if raw is None or isinstance(raw, bool):
            continue
        if isinstance(raw, (str, int)):
            found.add(str(raw))
    return sorted(found)


def _operation_dates(operations: dict[str, dict[str, object]]) -> list[str]:
    parsed: list[date] = []
    for row in operations.values():
        item = _parse_date(row.get("TimeOperation"))
        if item is not None:
            parsed.append(item)
    parsed.sort()
    return [item.isoformat() for item in parsed]


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _non_trade(types: list[str], operations: dict[str, dict[str, object]], incomplete: bool) -> str:
    if not operations and incomplete:
        return "unresolved"
    if not operations:
        return "unresolved"
    if any(item.casefold() != "trd" for item in types):
        return "yes"
    if incomplete:
        return "unresolved"
    return "no"


def _status_list(state: CollectedState) -> list[str]:
    names = list(_STATUS_ORDER)
    for name in state.query_status:
        if name not in names:
            names.append(name)
    return [f"{name}={state.query_status[name]}" for name in names if name in state.query_status]


def _observed_fields(state: CollectedState) -> list[str]:
    listed: list[str] = []
    for name in _STATUS_ORDER:
        rows = state.entities.get(name, {})
        if not rows:
            continue
        keys: set[str] = set()
        for row in rows.values():
            keys.update(str(key) for key in row)
        listed.append(f"{name}={{{', '.join(sorted(keys))}}}")
    return listed


def _value_encodings(
    positions: dict[str, dict[str, object]],
    balances: dict[str, dict[str, object]],
    operations: dict[str, dict[str, object]],
) -> list[str]:
    encodings: dict[str, str] = {}
    for row in list(positions.values()) + list(balances.values()) + list(operations.values()):
        for field_name in _SHAPE_FIELDS:
            if field_name not in row or field_name in encodings:
                continue
            encodings[field_name] = _json_shape(row[field_name])
    return [f"{name}={encodings[name]}" for name in sorted(encodings)]


def _json_shape(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "json_boolean"
    if isinstance(value, (int, float)):
        return "json_number"
    if isinstance(value, str):
        return "json_string"
    return "json_other"
