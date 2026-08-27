# ADR-0015: Alfa PRO compatibility fingerprint and safe diagnostics

Status: Implemented for R07-T01

## Context

The Alfa PRO adapter is a narrow, owner-triggered, read-only current-state
snapshot path. A successful transport or authentication handshake does not by
itself prove that the protocol and entity layout are still the layout understood
by the adapter. A layout change must never become a silently misapplied
snapshot.

The diagnostic artifact is intended to be copied to an owner or development
agent. It is therefore an aggregate of bounded structural observations only.
It must not contain router frames, source payloads, account or instrument
identifiers, names, financial values, credentials, endpoint paths, or exception
messages.

## Decision

The transient `BrokerSnapshot` contains an `AlfaDiagnosticReport` with two
versioned contracts:

- `alfa-pro-diagnostics/v1` is the owner-facing report contract.
- `alfa-pro-fingerprint/v1` is the deterministic SHA-256 fingerprint contract.

The fingerprint covers only the documented API version, bounded allowlisted
version hints, observed router message shapes, entity payload field names,
entity row field names, and capability labels. It does not cover row keys or
any field values. Version hints are read only from bounded allowlisted fields;
an absent or invalid hint remains `unresolved`.

Compatibility has three explicit states:

- `compatible`: the expected bus/query shapes and required current-state layout
  were observed, with no material protocol or layout anomaly.
- `unknown`: the observation is incomplete or a protocol/layout anomaly was
  seen; the adapter cannot prove safe compatibility.
- `unsupported`: an explicitly observed API/protocol version is outside the
  adapter contract.

Diagnostics classify the first actionable boundary as `connection`, `auth`,
`routing`, `protocol`, `layout`, or `mapping`. Failure codes are bounded,
developer-readable labels; raw provider error text is not copied into the
artifact.

## Safety and apply rules

The existing lifecycle remains authoritative: explicit refresh, preview,
owner mapping, explicit prepare/select decisions, and persisted staleness
fingerprints. `BrokerSnapshot.status` becomes `compatibility_error` when the
required read completes but compatibility is `unknown` or `unsupported`, and
`eligible_for_apply` remains false. The API does not refresh in the background,
does not broaden the channel allowlist, and does not bypass mapping or
staleness checks.

The preview response exposes both structured `diagnostics` and a text
`diagnostic_report`. The Alfa PRO panel displays the report behind an explicit
details disclosure and provides an owner-triggered copy action. The text form
repeats the safety assertions so it can be transferred without accompanying
application logs.

## Verification boundary

This task verifies the contract with synthetic/sanitized fixtures only. It
covers a compatible fingerprint, value-independent structural fingerprinting,
unknown router protocol, unknown entity layout, unsupported protocol version,
connection failure sanitization, mapping classification, and the existing
preview/apply staleness behavior. No live Alfa PRO probe or owner UAT is part
of this implementation or its verification.
