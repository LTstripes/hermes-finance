"""Safe compatibility and diagnostic contracts for Alfa PRO observations.

The contract deliberately describes protocol shape, not provider data.  It is
safe to expose to an owner or a development agent because it never contains
raw frames, account identifiers, instrument identifiers, names, credentials,
or financial values.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

DIAGNOSTIC_SCHEMA_VERSION = "alfa-pro-diagnostics/v1"
FINGERPRINT_SCHEMA_VERSION = "alfa-pro-fingerprint/v1"
DEFAULT_API_DOC_VERSION = "2.1"
KNOWN_PROTOCOL_FAMILY = "router-v1"
KNOWN_LAYOUT_FAMILY = "snapshot-v2.1"

REQUIRED_SNAPSHOT_ENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "ClientAccountEntity": ("IdAccount",),
    "ClientSubAccountEntity": ("IdAccount", "IdSubAccount"),
    "SubAccountRazdelEntity": ("IdAccount", "IdSubAccount", "IdRazdel"),
    "ClientPositionEntity": (
        "IdAccount",
        "IdSubAccount",
        "IdRazdel",
        "IdPosition",
        "IdObject",
        "TorgPos",
    ),
    "ClientBalanceEntity": ("DataId", "IdAccount", "Money"),
}

_PAYLOAD_LIST_FIELDS = frozenset({"Data", "Updated", "Deleted"})
_VERSION_FIELDS = {
    "alfa_pro_version": ("AlfaProVersion", "AlfaVersion", "ProductVersion", "ClientVersion"),
    "api_version": ("ApiVersion", "APIVersion", "ApiDocVersion"),
    "protocol_version": ("ProtocolVersion", "RouterProtocolVersion"),
}
_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
_SAFE_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
MAX_SAFE_FIELDS_PER_ENTITY = 128


class AlfaCompatibilityState(StrEnum):
    """Whether the observed shape is safe to use with the current adapter."""

    COMPATIBLE = "compatible"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class AlfaDiagnosticFailureClass(StrEnum):
    """The first actionable failure boundary in an Alfa observation."""

    NONE = "none"
    CONNECTION = "connection"
    AUTH = "auth"
    ROUTING = "routing"
    PROTOCOL = "protocol"
    LAYOUT = "layout"
    MAPPING = "mapping"


@dataclass(frozen=True, slots=True)
class CompatibilityEvaluation:
    compatibility_state: AlfaCompatibilityState
    compatibility_fingerprint: str | None
    observed_alfa_pro_version: str | None
    observed_api_version: str | None
    observed_protocol_version: str | None
    protocol_family: str
    layout_family: str
    capabilities: tuple[str, ...]
    failure_class: AlfaDiagnosticFailureClass
    failure_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlfaDiagnosticReport:
    """A bounded, structured artifact intended to be safe to share."""

    schema_version: str = DIAGNOSTIC_SCHEMA_VERSION
    provider: str = "alfa_pro"
    snapshot_status: str = "unresolved"
    eligible_for_apply: bool = False
    compatibility_state: AlfaCompatibilityState = AlfaCompatibilityState.UNKNOWN
    compatibility_fingerprint: str | None = None
    api_doc_version: str = DEFAULT_API_DOC_VERSION
    observed_alfa_pro_version: str | None = None
    observed_api_version: str | None = None
    observed_protocol_version: str | None = None
    protocol_family: str = "unresolved"
    layout_family: str = "unresolved"
    capabilities: tuple[str, ...] = ()
    failure_class: AlfaDiagnosticFailureClass = AlfaDiagnosticFailureClass.NONE
    failure_codes: tuple[str, ...] = ()
    entity_status: tuple[str, ...] = ()
    entity_counts: tuple[str, ...] = ()
    observed_fields: tuple[str, ...] = ()
    raw_payload_saved: bool = False
    private_values_included: bool = False
    credentials_included: bool = False

    def with_snapshot(self, *, status: str, eligible_for_apply: bool) -> AlfaDiagnosticReport:
        return replace(
            self,
            snapshot_status=status,
            eligible_for_apply=eligible_for_apply,
        )

    def with_failure(
        self,
        failure_class: AlfaDiagnosticFailureClass,
        *failure_codes: str,
    ) -> AlfaDiagnosticReport:
        codes = tuple(dict.fromkeys(failure_codes))
        return replace(self, failure_class=failure_class, failure_codes=codes)

    def to_dict(self) -> dict[str, object]:
        safe_artifact = not (
            self.raw_payload_saved or self.private_values_included or self.credentials_included
        )
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "snapshot_status": self.snapshot_status,
            "eligible_for_apply": self.eligible_for_apply,
            "compatibility_state": self.compatibility_state.value,
            "compatibility_fingerprint": self.compatibility_fingerprint,
            "api_doc_version": self.api_doc_version,
            "observed_alfa_pro_version": self.observed_alfa_pro_version,
            "observed_api_version": self.observed_api_version,
            "observed_protocol_version": self.observed_protocol_version,
            "protocol_family": self.protocol_family,
            "layout_family": self.layout_family,
            "capabilities": list(self.capabilities),
            "failure_class": self.failure_class.value,
            "failure_codes": list(self.failure_codes),
            "entity_status": list(self.entity_status),
            "entity_counts": list(self.entity_counts),
            "observed_fields": list(self.observed_fields),
            "safe_artifact": safe_artifact,
            "raw_payload_saved": self.raw_payload_saved,
            "private_values_included": self.private_values_included,
            "credentials_included": self.credentials_included,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def to_text(self) -> str:
        def joined(values: Iterable[str]) -> str:
            return ", ".join(values) if values else ""

        lines = [
            f"schema_version: {self.schema_version}",
            f"provider: {self.provider}",
            f"snapshot_status: {self.snapshot_status}",
            f"eligible_for_apply: {'yes' if self.eligible_for_apply else 'no'}",
            f"compatibility_state: {self.compatibility_state.value}",
            f"compatibility_fingerprint: {self.compatibility_fingerprint or 'unresolved'}",
            f"api_doc_version: {self.api_doc_version}",
            f"observed_alfa_pro_version: {self.observed_alfa_pro_version or 'unresolved'}",
            f"observed_api_version: {self.observed_api_version or 'unresolved'}",
            f"observed_protocol_version: {self.observed_protocol_version or 'unresolved'}",
            f"protocol_family: {self.protocol_family}",
            f"layout_family: {self.layout_family}",
            f"failure_class: {self.failure_class.value}",
            f"failure_codes: [{joined(self.failure_codes)}]",
            f"capabilities: [{joined(self.capabilities)}]",
            f"entity_status: [{joined(self.entity_status)}]",
            f"entity_counts: [{joined(self.entity_counts)}]",
            f"observed_fields: [{joined(self.observed_fields)}]",
            f"safe_artifact: {'yes' if not (self.raw_payload_saved or self.private_values_included or self.credentials_included) else 'no'}",
            f"raw_payload_saved: {'yes' if self.raw_payload_saved else 'no'}",
            f"private_values_included: {'yes' if self.private_values_included else 'no'}",
            f"credentials_included: {'yes' if self.credentials_included else 'no'}",
        ]
        return "\n".join(lines) + "\n"


def extract_version_hints(payload: object) -> dict[str, str | None]:
    """Read only bounded version hints from a connection-state object."""

    if not isinstance(payload, dict):
        return {name: None for name in _VERSION_FIELDS}
    roots: list[Mapping[str, object]] = [payload]
    states = payload.get("States")
    if isinstance(states, dict):
        roots.insert(0, states)
    result: dict[str, str | None] = {}
    for name, keys in _VERSION_FIELDS.items():
        result[name] = None
        for root in roots:
            for key in keys:
                value = _safe_version(root.get(key))
                if value is not None:
                    result[name] = value
                    break
            if result[name] is not None:
                break
    return result


def evaluate_compatibility(
    *,
    api_doc_version: str,
    observed_alfa_pro_version: str | None,
    observed_api_version: str | None,
    observed_protocol_version: str | None,
    message_shapes: Iterable[str],
    entity_payload_fields: Mapping[str, Iterable[str]],
    entity_fields: Mapping[str, Iterable[str]],
    protocol_anomalies: Iterable[str] = (),
    layout_anomalies: Iterable[str] = (),
) -> CompatibilityEvaluation:
    """Evaluate only structural observations; values are never consulted."""

    shapes = frozenset(str(item) for item in message_shapes)
    protocol_issues = tuple(sorted(set(str(item) for item in protocol_anomalies)))
    layout_issues = tuple(sorted(set(str(item) for item in layout_anomalies)))
    payload_fields = _normalise_field_map(entity_payload_fields)
    row_fields = _normalise_field_map(entity_fields)
    capabilities = _capabilities(row_fields)

    required_payload_seen = all(name in payload_fields for name in REQUIRED_SNAPSHOT_ENTITY_FIELDS)
    required_payload_shape_ok = all(
        _PAYLOAD_LIST_FIELDS.intersection(payload_fields.get(name, ()))
        for name in REQUIRED_SNAPSHOT_ENTITY_FIELDS
    )
    required_rows_shape_ok = all(
        all(field in row_fields.get(name, ()) for field in required_fields)
        for name, required_fields in REQUIRED_SNAPSHOT_ENTITY_FIELDS.items()
        if row_fields.get(name)
    )
    protocol_observed = bool({"connection_state_bus", "entity_response"}.issubset(shapes))
    protocol_family = (
        KNOWN_PROTOCOL_FAMILY if protocol_observed and not protocol_issues else "unresolved"
    )
    layout_observed = required_payload_seen and required_payload_shape_ok and required_rows_shape_ok
    layout_family = KNOWN_LAYOUT_FAMILY if layout_observed and not layout_issues else "unresolved"

    fingerprint = (
        _fingerprint(
            api_doc_version=api_doc_version,
            observed_alfa_pro_version=observed_alfa_pro_version,
            observed_api_version=observed_api_version,
            observed_protocol_version=observed_protocol_version,
            message_shapes=shapes,
            entity_payload_fields=payload_fields,
            entity_fields=row_fields,
            capabilities=capabilities,
        )
        if shapes or payload_fields or row_fields
        else None
    )

    # Version hints are observational until an accepted contract proves their
    # namespace and supported values. Structural protocol/layout guards remain
    # the compatibility decision for the current adapter contract.
    if protocol_issues or not protocol_observed:
        codes = protocol_issues or ("protocol_shape_unresolved",)
        return CompatibilityEvaluation(
            compatibility_state=AlfaCompatibilityState.UNKNOWN,
            compatibility_fingerprint=fingerprint,
            observed_alfa_pro_version=observed_alfa_pro_version,
            observed_api_version=observed_api_version,
            observed_protocol_version=observed_protocol_version,
            protocol_family=protocol_family,
            layout_family=layout_family,
            capabilities=capabilities,
            failure_class=AlfaDiagnosticFailureClass.PROTOCOL,
            failure_codes=tuple(codes),
        )
    if layout_issues or not layout_observed:
        codes = layout_issues or ("snapshot_layout_unresolved",)
        return CompatibilityEvaluation(
            compatibility_state=AlfaCompatibilityState.UNKNOWN,
            compatibility_fingerprint=fingerprint,
            observed_alfa_pro_version=observed_alfa_pro_version,
            observed_api_version=observed_api_version,
            observed_protocol_version=observed_protocol_version,
            protocol_family=protocol_family,
            layout_family=layout_family,
            capabilities=capabilities,
            failure_class=AlfaDiagnosticFailureClass.LAYOUT,
            failure_codes=tuple(codes),
        )
    return CompatibilityEvaluation(
        compatibility_state=AlfaCompatibilityState.COMPATIBLE,
        compatibility_fingerprint=fingerprint,
        observed_alfa_pro_version=observed_alfa_pro_version,
        observed_api_version=observed_api_version,
        observed_protocol_version=observed_protocol_version,
        protocol_family=protocol_family,
        layout_family=layout_family,
        capabilities=capabilities,
        failure_class=AlfaDiagnosticFailureClass.NONE,
        failure_codes=(),
    )


def diagnostic_from_evaluation(
    evaluation: CompatibilityEvaluation,
    *,
    api_doc_version: str,
    entity_status: Iterable[str] = (),
    entity_counts: Iterable[str] = (),
    observed_fields: Iterable[str] = (),
) -> AlfaDiagnosticReport:
    return AlfaDiagnosticReport(
        api_doc_version=api_doc_version,
        compatibility_state=evaluation.compatibility_state,
        compatibility_fingerprint=evaluation.compatibility_fingerprint,
        observed_alfa_pro_version=evaluation.observed_alfa_pro_version,
        observed_api_version=evaluation.observed_api_version,
        observed_protocol_version=evaluation.observed_protocol_version,
        protocol_family=evaluation.protocol_family,
        layout_family=evaluation.layout_family,
        capabilities=evaluation.capabilities,
        failure_class=evaluation.failure_class,
        failure_codes=evaluation.failure_codes,
        entity_status=tuple(entity_status),
        entity_counts=tuple(entity_counts),
        observed_fields=tuple(observed_fields),
    )


def diagnostic_for_failure(
    *,
    api_doc_version: str,
    failure_class: AlfaDiagnosticFailureClass,
    failure_code: str,
    snapshot_status: str,
) -> AlfaDiagnosticReport:
    return AlfaDiagnosticReport(
        api_doc_version=api_doc_version,
        snapshot_status=snapshot_status,
        failure_class=failure_class,
        failure_codes=(failure_code,),
    )


def _safe_version(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _SAFE_VERSION.fullmatch(text) else None


def _normalise_field_map(mapping: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    return {str(entity): safe_field_names(fields) for entity, fields in mapping.items()}


def safe_field_names(fields: Iterable[str]) -> tuple[str, ...]:
    """Keep only bounded protocol field labels; never echo arbitrary keys."""

    return tuple(
        sorted({field for field in (str(item) for item in fields) if _SAFE_FIELD.fullmatch(field)})[
            :MAX_SAFE_FIELDS_PER_ENTITY
        ]
    )


def _capabilities(entity_fields: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    capability_fields = {
        ("ClientAccountEntity", "IdAccount"): "account_identity",
        ("ClientSubAccountEntity", "IdAccount"): "subaccount_account_link",
        ("SubAccountRazdelEntity", "IdAccount"): "section_account_link",
        ("SubAccountRazdelEntity", "IdSubAccount"): "section_subaccount_link",
        ("ClientPositionEntity", "IdAccount"): "position_account_link",
        ("ClientPositionEntity", "IdSubAccount"): "position_subaccount_link",
        ("ClientPositionEntity", "IdRazdel"): "position_section_link",
        ("ClientPositionEntity", "IdObject"): "position_instrument_identity",
        ("ClientPositionEntity", "TorgPos"): "position_quantity",
        ("ClientPositionEntity", "Price"): "position_broker_unit_price",
        ("ClientPositionEntity", "UchPrice"): "position_accounting_price",
        ("ClientPositionEntity", "NKD"): "position_nkd",
        ("ClientPositionEntity", "NPLtoMarketCurPrice"): "position_unrealized_result",
        ("ClientPositionEntity", "IsMoney"): "position_money_flag",
        ("ClientBalanceEntity", "Money"): "cash_amount",
        ("AssetInfoEntity", "ISIN"): "instrument_isin",
        ("AssetInfoEntity", "Ticker"): "instrument_ticker",
        ("AssetInfoEntity", "Name"): "instrument_name",
    }
    return tuple(
        sorted(
            capability
            for (entity, field), capability in capability_fields.items()
            if field in set(entity_fields.get(entity, ()))
        )
    )


def _fingerprint(
    *,
    api_doc_version: str,
    observed_alfa_pro_version: str | None,
    observed_api_version: str | None,
    observed_protocol_version: str | None,
    message_shapes: Iterable[str],
    entity_payload_fields: Mapping[str, Iterable[str]],
    entity_fields: Mapping[str, Iterable[str]],
    capabilities: Iterable[str],
) -> str:
    observation = {
        "fingerprint_schema": FINGERPRINT_SCHEMA_VERSION,
        "api_doc_version": api_doc_version,
        "observed_alfa_pro_version": observed_alfa_pro_version or "unresolved",
        "observed_api_version": observed_api_version or "unresolved",
        "observed_protocol_version": observed_protocol_version or "unresolved",
        "message_shapes": sorted(set(message_shapes)),
        "entity_payload_fields": {
            entity: sorted(set(fields)) for entity, fields in sorted(entity_payload_fields.items())
        },
        "entity_fields": {
            entity: sorted(set(fields)) for entity, fields in sorted(entity_fields.items())
        },
        "capabilities": sorted(set(capabilities)),
    }
    encoded = json.dumps(observation, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
