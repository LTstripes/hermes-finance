"""Lossless v2 representation of already allowlisted AI facts, never a calculator.

Payload references identify exact JSON values, not operations or source entities.
Account/interval occurrences retain their order, multiplicity and financial scope.
"""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256

VERSION = "2.0.0"
SCHEMA_URI = "https://hermes-finance.local/schema/ai-financial-review/2.0.0/schema.json"
LEGACY_VERSIONS = {"1.4.0", "1.5.0"}
TABLE_PREFIXES = {
    "instruments": "instrument-",
    "endpoints": "endpoint-",
    "results": "result-",
    "events": "event-",
}
IDENTITY_FIELDS = ("isin", "name", "instrument_type")
RESULT_FIELDS = ("metrics", "components", "coverage", "reason_codes", "assumptions")
INSTRUMENT_FIELDS = (*IDENTITY_FIELDS, "opening", "closing", *RESULT_FIELDS, "events")
GUIDE = {
    "lookup": "Resolve typed refs in source_payloads. Each exact payload is stored once.",
    "context": "Each instrument occurrence retains its own account and interval context.",
    "identity": "Payload refs identify values, not unique transactions, securities or accounts.",
    "multiplicity": "Ordered event_refs preserve every occurrence, including repeated equal refs.",
    "counting": "Do not sum payload tables or overlapping intervals. Use the enclosing result and its inclusion rules.",
    "windows": "Event payloads retain interval-specific NULL amounts, eligibility, cash dates and per-leg inclusion.",
    "revisions": "Different values or revision states remain distinct payloads; other revision histories are unchanged.",
}


class PayloadReferenceError(ValueError):
    """A lossless source-payload representation cannot be established."""


def _encoded(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _ref(table: str, value: object) -> str:
    return TABLE_PREFIXES[table] + sha256(_encoded(value).encode("utf-8")).hexdigest()[:32]


def _instrument_slots(report):
    """Visit only the two normative source-analysis locations, never arbitrary dicts."""
    sections = report["sections"]
    source = sections.get("source_returns", {}).get("data")
    if source is not None:
        for account in source["accounts"]:
            for interval in account["intervals"]:
                for index in range(len(interval["instruments"])):
                    yield interval["instruments"], index
    overall = sections.get("returns_overall", {}).get("data")
    if overall is not None:
        for instrument in overall["instruments"]:
            for account in instrument["accounts"]:
                if account["detail"] is not None:
                    yield account["detail"], "analysis"


def normalize_source_payloads(report: dict[str, object]) -> dict[str, object]:
    """Represent a v1 report without discarding or inferring any source fact."""
    if report.get("schema_version") not in LEGACY_VERSIONS or "source_payloads" in report:
        raise PayloadReferenceError("expected an expanded v1 AI report")
    result = deepcopy(report)
    tables = {table: {} for table in TABLE_PREFIXES}

    def intern(table, value):
        reference = _ref(table, value)
        previous = tables[table].get(reference)
        if reference in tables[table] and _encoded(previous) != _encoded(value):
            raise PayloadReferenceError("payload reference collision")
        tables[table][reference] = value
        return reference

    for container, key in _instrument_slots(result):
        item = container[key]
        if set(item) != set(INSTRUMENT_FIELDS):
            raise PayloadReferenceError("unexpected source instrument fields")
        container[key] = {
            "isin": item["isin"],
            "instrument_ref": intern("instruments", {name: item[name] for name in IDENTITY_FIELDS}),
            "opening_ref": intern("endpoints", item["opening"]),
            "closing_ref": intern("endpoints", item["closing"]),
            "result_ref": intern("results", {name: item[name] for name in RESULT_FIELDS}),
            "event_refs": [intern("events", event) for event in item["events"]],
        }
    dictionary = {
        "expanded_schema": report["$schema"],
        "expanded_schema_version": report["schema_version"],
        "reading_guide": dict(GUIDE),
        **{table: dict(sorted(values.items())) for table, values in tables.items()},
    }
    result["$schema"] = SCHEMA_URI
    result["schema_version"] = VERSION
    # Put the lookup tables before their first use, without reordering v1 fields.
    return {
        name: value
        for key, item in result.items()
        for name, value in (
            (("source_payloads", dictionary), (key, item)) if key == "sections" else ((key, item),)
        )
    }


def _resolve_source_payloads(report: dict[str, object], *, expand: bool) -> dict[str, object]:
    if report.get("schema_version") != VERSION:
        raise PayloadReferenceError("expected a normalized v2 AI report")
    result = deepcopy(report) if expand else report
    dictionary = result.pop("source_payloads") if expand else result["source_payloads"]
    if dictionary["expanded_schema_version"] not in LEGACY_VERSIONS:
        raise PayloadReferenceError("unsupported expanded schema version")
    used = {table: set() for table in TABLE_PREFIXES}
    for table in TABLE_PREFIXES:
        for reference, value in dictionary[table].items():
            if reference != _ref(table, value):
                raise PayloadReferenceError("payload reference does not match its value")

    def resolve(table, reference):
        if not isinstance(reference, str) or reference not in dictionary[table]:
            raise PayloadReferenceError("unresolved or incorrectly typed payload reference")
        used[table].add(reference)
        # Different occurrences must never share a mutable expanded value.
        value = dictionary[table][reference]
        return deepcopy(value) if expand else value

    for container, key in _instrument_slots(result):
        item = container[key]
        identity = resolve("instruments", item["instrument_ref"])
        if identity["isin"] != item["isin"]:
            raise PayloadReferenceError("instrument reference conflicts with occurrence ISIN")
        values = resolve("results", item["result_ref"])
        expanded = {
            **identity,
            "opening": resolve("endpoints", item["opening_ref"]),
            "closing": resolve("endpoints", item["closing_ref"]),
            **values,
            "events": [resolve("events", reference) for reference in item["event_refs"]],
        }
        if expand:
            container[key] = expanded
    if any(used[table] != set(dictionary[table]) for table in TABLE_PREFIXES):
        raise PayloadReferenceError("unreferenced payload in AI report")
    if expand:
        result["$schema"] = dictionary["expanded_schema"]
        result["schema_version"] = dictionary["expanded_schema_version"]
    return result


def validate_source_payload_refs(report: dict[str, object]) -> None:
    """Check all links and exact payloads without rebuilding the expanded report."""
    _resolve_source_payloads(report, expand=False)


def expand_source_payloads(report: dict[str, object]) -> dict[str, object]:
    """Resolve v2 exactly, rejecting orphaned, changed or incorrectly typed refs."""
    return _resolve_source_payloads(report, expand=True)
