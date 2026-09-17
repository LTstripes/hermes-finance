# Hermes Finance v0.9.0 — release candidate

> **Status:** PREPARED / UAT-PENDING
>
> This is a release candidate for owner OPS03 Preview/UAT. It is not a
> published tag or GitHub Release. Published Stable remains `v0.8.2` until
> owner UAT passes and the guarded release flow is explicitly invoked.

## What is included

The candidate gathers the accepted product and runtime work integrated after
the published `v0.8.2` release:

- Decision Support v1, including deterministic Scenario Lab and owner-facing
  decision surfaces;
- Performance v1 with exact portfolio/account XIRR and TWRR, valuation and
  flow hardening, and explicit exact-zero versus unavailable semantics;
- bounded PERF04A/B/C decomposition and reconciliation evidence, without
  unsupported instrument-level P&L attribution;
- linked asset and credit-card debt integrity, linked financing safeguards,
  and canonical AI financial-review/export hardening;
- explicit OPS01 Prepare + deterministic Start and OPS02 immutable published
  Stable update operations;
- OPS03 exact-SHA isolated Preview/UAT preparation;
- CI and release-safety improvements that preserve synthetic, private-safe
  verification.

## Release boundary

- UI v2 remains a separate workstream and is not included in `0.9.0`.
- This release-prep task changes release identity and documentation only; it
  adds no migration, formula, provider, runtime-data or network behavior.
- The canonical Alembic head remains `0041_debt_linked_account`.
- The application remains local-only, single-user and loopback-bound to
  `127.0.0.1:8000`; unknown or unavailable financial evidence remains explicit.

## Verification and next step

The candidate must be integrated at one exact canonical SHA, then prepared by
OPS03 as an isolated Preview/UAT runtime pinned to that SHA. Only an owner
`PASS` permits guarded publication of `v0.9.0`; after publication, OPS02 will
perform the first real Stable transition `v0.8.2 -> v0.9.0`.
