"""Sanitized aggregate evidence. Counts, field names and labels only."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from hermes_finance.alfa_pro_probe.channels import API_DOC_VERSION
from hermes_finance.alfa_pro_probe.reader import CollectedState

_IIS_KEY_RE = re.compile(r"iis", re.IGNORECASE)
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


@dataclass
class ProbeReport:
    alfa_pro_version: str = "unresolved"
    api_doc_version: str = API_DOC_VERSION
    connection: str = "unresolved"
    authenticated_read: str = "unresolved"
    ready_to_sign_observed: str = "unresolved"
    accounts_count: int = 0
    subaccounts_count: int = 0
    iis_explicitly_classifiable: str = "unresolved"
    positions_count: int = 0
    positions_with_isin: str = "0/0"
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
    accounts_id_fingerprint: str = "unresolved"
    subaccounts_id_fingerprint: str = "unresolved"
    instruments_id_fingerprint: str = "unresolved"
    operations_id_fingerprint: str = "unresolved"
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
            "",
            f"accounts_count: {self.accounts_count}",
            f"subaccounts_count: {self.subaccounts_count}",
            f"iis_explicitly_classifiable: {self.iis_explicitly_classifiable}",
            "",
            f"positions_count: {self.positions_count}",
            f"positions_with_isin: {self.positions_with_isin}",
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
        if self.accounts_id_fingerprint != "unresolved":
            lines.extend(
                [
                    "",
                    "id_fingerprints:",
                    f"  accounts: {self.accounts_id_fingerprint}",
                    f"  subaccounts: {self.subaccounts_id_fingerprint}",
                    f"  instruments: {self.instruments_id_fingerprint}",
                    f"  operations: {self.operations_id_fingerprint}",
                ]
            )
        if self.value_encodings:
            lines.append("value_encodings: [" + ", ".join(self.value_encodings) + "]")
        if self.channels_invoked:
            lines.append("channels_invoked: [" + ", ".join(self.channels_invoked) + "]")
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines) + "\n"


def build_report(state: CollectedState, *, connection: str) -> ProbeReport:
    accounts = state.entities.get("ClientAccountEntity", {})
    subaccounts = state.entities.get("ClientSubAccountEntity", {})
    razdels = state.entities.get("SubAccountRazdelEntity", {})
    positions = state.entities.get("ClientPositionEntity", {})
    balances = state.entities.get("ClientBalanceEntity", {})
    operations = state.entities.get("ClientOperationEntity", {})
    assets = state.entities.get("AssetInfoEntity", {})

    isin_by_object = _isin_presence(assets)
    with_isin = 0
    for row in positions.values():
        object_id = row.get("IdObject")
        if str(object_id) in isin_by_object:
            with_isin += 1

    types = _operation_types(operations)
    dates = _operation_dates(operations)
    encodings = _value_encodings(positions, balances, operations)

    report = ProbeReport(
        connection=connection,
        authenticated_read=_authenticated_read(state, connection),
        ready_to_sign_observed=_ready_label(state.ready_to_sign),
        accounts_count=len(accounts),
        subaccounts_count=len(subaccounts),
        iis_explicitly_classifiable=_iis_classifiable(accounts, subaccounts, razdels),
        positions_count=len(positions),
        positions_with_isin=f"{with_isin}/{len(positions)}",
        cash_balance_entities_count=len(balances),
        snapshot_fields=_snapshot_fields(positions, balances),
        operations_count=len(operations),
        oldest_operation_date=dates[0] if dates else "unresolved",
        newest_operation_date=dates[-1] if dates else "unresolved",
        observed_operation_types=types,
        non_trade_ledger_events_observed=_non_trade(types, operations),
        accounts_id_fingerprint=_fingerprint(accounts),
        subaccounts_id_fingerprint=_fingerprint(subaccounts),
        instruments_id_fingerprint=_fingerprint(_instrument_ids(positions, assets)),
        operations_id_fingerprint=_fingerprint(operations),
        value_encodings=encodings,
        channels_invoked=list(state.channels_invoked),
        raw_payload_saved="no",
        private_values_printed="no",
        trading_methods_invoked="no",
    )
    if state.ready_to_sign is False and report.authenticated_read == "pass":
        report.read_with_ready_to_sign_false = "pass"
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
    return f"{name}: probe failed"


def _authenticated_read(state: CollectedState, connection: str) -> str:
    if connection != "pass":
        return "fail"
    if state.auth_status != 2:
        return "fail"
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


def _iis_classifiable(*groups: dict[str, dict[str, object]]) -> str:
    for group in groups:
        for row in group.values():
            for key in row:
                if _IIS_KEY_RE.search(str(key)):
                    return "yes"
    return "unresolved"


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


def _non_trade(types: list[str], operations: dict[str, dict[str, object]]) -> str:
    if not operations:
        return "unresolved"
    if any(item.casefold() != "trd" for item in types):
        return "yes"
    return "no"


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


def _instrument_ids(
    positions: dict[str, dict[str, object]],
    assets: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    ids: dict[str, dict[str, object]] = {}
    for row in positions.values():
        object_id = row.get("IdObject")
        if object_id is not None and not isinstance(object_id, bool):
            ids[str(object_id)] = {"id": object_id}
        fi = row.get("IdFiBalance")
        if fi is not None and not isinstance(fi, bool):
            ids[f"fi:{fi}"] = {"id": fi}
    for key, row in assets.items():
        ids.setdefault(key, row)
    return ids


def _fingerprint(rows: dict[str, object]) -> str:
    material = "\n".join(sorted(rows)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]
