# Hermes Finance v0.9.0

> **Status:** PUBLISHED / OWNER UAT PASS
> **Published:** 2026-09-17
> **Exact released code:** `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`

Hermes Finance `v0.9.0` is the first release to prove the redesigned owner runtime/release lifecycle end to end on a real Stable transition.

## What is included

The release gathers accepted work integrated after `v0.8.2`:

- Decision Support v1, including deterministic Scenario Lab and owner-facing decision surfaces;
- Performance v1 with exact portfolio/account XIRR and TWRR, valuation/flow hardening, and explicit exact-zero versus unavailable semantics;
- bounded PERF04A/B/C decomposition and reconciliation evidence without unsupported instrument-level P&L attribution;
- linked asset / credit-card debt integrity, linked-financing safeguards, and AI financial-review/export hardening;
- OPS01 explicit Prepare + deterministic Start;
- OPS02 explicit immutable Stable release update;
- OPS03 exact-SHA isolated Preview/UAT preparation;
- CI and release-safety improvements that preserve private-safe verification.

## Runtime/release improvement

The Windows launcher intentionally remains familiar. The important change is architectural: the old launcher-owned Stable self-update state machine is no longer the canonical update path.

Responsibilities are now separated:

- launcher — owner-facing profile/status/Start/Stop shell;
- `prepare-runtime.ps1` — exact Prepare/Validate;
- `start-local.ps1` — deterministic Start;
- `update-stable.ps1` — explicit update to one selected published immutable release;
- `prepare-preview.ps1` — isolated exact-SHA Preview/UAT preparation;
- issue #124 — guarded immutable release publication.

This reduces blast radius and makes failures attributable to one bounded operation instead of a large state machine.

## Owner acceptance

### OPS03 Preview/UAT — PASS

The exact release code `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36` passed owner UAT in an isolated Preview against a verified copy of owner data. Production data remained isolated.

### OPS02 Stable transition — PASS

The first real release-to-release transition succeeded:

`v0.8.2 -> v0.9.0`

OPS02 proved the published annotated target, created a verified production SQLite backup before Git mutation, pinned Stable to the exact release commit, ran target Prepare + Validate, and stopped without auto-start or migration. The production DB hash remained unchanged during the update operation.

### Production Start — PASS

After explicit Start on Stable `v0.9.0`:

- production readiness smoke passed;
- `/api/health` returned `status=ok`, `version=0.9.0`;
- owner confirmed data continuity.

## Release boundary

- UI v2 remains a separate workstream and is not included in `v0.9.0`.
- Canonical Alembic head is `0041_debt_linked_account`.
- The application remains local-only, single-user and loopback-bound to `127.0.0.1:8000`.
- Unknown/unavailable financial evidence remains explicit.
- No cloud/auth/telemetry/trading/provider-write/background-refresh behavior was added by release preparation.

## Publication evidence

- Exact-main CI #700 / run `35207551120`: SUCCESS.
- Guarded Release #253 / run `35235369797`: SUCCESS.
- Annotated tag object: `07c06d44f8b780e721be346a21909ca02585d57d`.
- Tag peels exactly to `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`.
- GitHub Release: published, draft=false, prerelease=false.

Known non-blocking metadata follow-up: #410 corrects the GitHub Release description that inherited pre-publication `UAT-PENDING` wording. The published code/tag identity is unaffected.

Detailed runtime/release closeout: `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`.
