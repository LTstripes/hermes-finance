# Hermes Finance

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Оно помогает закрывать месяц, видеть ликвидный капитал и долги, анализировать инвестиционный результат и пассивный доход, работать с целями/Tax/IIS/Scenario Lab, проверять reconciliation/freshness и экспортировать read-only AI Analysis Bundle.

## Current status

Published Stable: **v0.8.2** (2026-09-05).

- annotated tag object: `bfa1194d4151bb72882f4230f144b039d240eda9`;
- released peeled commit: `a22542d7b20ebdf34e38384004162d409f163ab3`.

Canonical development `main` at the 2026-09-16 checkpoint:

`e5c09d55a21d4d4a25a9505a819977ed9a162f8c`

Exact-main CI: **#688 / run `35137779786` — SUCCESS**.

Merged development work does **not** become Stable automatically. Release publication remains a separate guarded owner action.

Current detailed checkpoint: [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md).

## Product/runtime invariants

- Windows 10/11, single user, local-only.
- Production binds only to `127.0.0.1:8000`.
- Local SQLite database.
- No cloud account, auth, telemetry, trading or background provider refresh.
- Provider/network reads happen only after explicit owner actions.
- Production Stable data, Preview/UAT data, `.env`, backups, credentials and private exports never enter agent/development workspaces.
- Closed months remain immutable until explicit Reopen.
- Backend/domain financial semantics are authoritative; frontend does not invent formulas.
- Exact money uses Decimal / integer minor units; unknown/unavailable is never silently converted to zero.

## Major completed lines

### Monthly Close / owner workflow

Guided Monthly Close is implemented and has passed owner UAT. The canonical workflow remains server-owned and fail-closed where evidence is incomplete.

### Decision Support v1

Completed and integrated:

- AI Analysis Bundle;
- Monthly Close Cockpit;
- Cash-flow Ladder / upcoming treasury events;
- Risk & Allocation;
- Freshness & Provenance;
- Reconciliation Center;
- current-state Tax/IIS Planner Lite;
- deterministic Insights backend;
- Scenario Lab v1.

Closeout: [`docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md`](docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md).

### Performance v1

Completed and integrated:

- portfolio/account XIRR;
- portfolio/account exact TWRR;
- flow/valuation/membership/transfer/in-kind fail-closed hardening;
- PERF04A `value_change_after_external_flows` monetary bridge;
- exact-zero versus unavailable/null semantics.

Closeout: [`docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`](docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md).

### PERF04B / PERF04C decomposition

#396 accepted **PARTIAL GO** for the exact backend decomposition:

```text
B_portfolio = Σ B_account + Σ T_internal_transfer
```

`B` is the existing PERF04A `value_change_after_external_flows`, not investment return/profit/P&L attribution.

#400 / PR #402 implemented the bounded backend read model and is canonical on current `main`.

Important safety boundaries:

- `100 → 99` without accepted reconciliation evidence is unavailable/null, not exact `-1`;
- `S>D` requires fee/commission/tax evidence explaining the full difference;
- `D>S` is unavailable;
- `fx_conversion_spread` alone does not authorize an exact PERF04C transfer effect;
- no partial split or residual bucket;
- instrument/asset-class, price-vs-FX, realised/unrealised and lot/cost-basis attribution remain unsupported.

Contract: [`docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`](docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md).

This slice is currently backend-only; API/UI exposure is a separate future decision.

## Requirements

- Windows 10/11;
- Python 3.13;
- [uv](https://docs.astral.sh/uv/);
- Node.js 22.22+ and npm;
- modern browser.

Docker/PostgreSQL/public web hosting are not required for the local product.

## Development installation

From a clean development checkout:

```powershell
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
```

Backend dependencies are locked by `backend/uv.lock`; frontend dependencies by `frontend/package-lock.json`.

Do not use a production runtime checkout as an agent/development workspace.

## Windows launcher — current role

The launcher is **not retired**.

It remains useful as the owner-facing shell for the currently configured Stable/Preview runtime profiles:

- profile/status presentation;
- ordinary Start/Stop;
- open Hermes after health is ready;
- diagnostics;
- installed Desktop/Start-menu shortcuts.

The historical launcher-owned Stable self-update experiment (#298/#311/#312) is **not** the canonical update path and must not be revived as another large state machine.

If the current `v0.8.2` launcher is already installed, open **Hermes Finance** from the existing Desktop/Start-menu shortcut and use the current pinned profile normally.

To install/reinstall the launcher from the published Stable checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\windows\install.ps1
```

Detailed owner operations: [`docs/OWNER_RUNTIME_OPERATIONS.md`](docs/OWNER_RUNTIME_OPERATIONS.md).

## Explicit Prepare + deterministic Start

The accepted runtime redesign (#313) separates operations instead of putting them all inside the launcher.

For a checkout containing OPS01:

```powershell
$checkout = (Get-Location).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Prepare
```

Validate existing preparation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Validate
```

Start an already prepared runtime:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Short smoke with automatic exit:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

Prepare installs only required locked dependencies, builds the production frontend and records ignored exact-build proof. Ordinary Start validates that proof and does not silently build, install dependencies or move Git refs.

## Explicit Stable release update

OPS02 (#386 / PR #393) implements a separate owner operation for one explicit immutable published release.

Run it from a trusted **control checkout outside the mutable Stable checkout**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

The operation proves the published annotated target, performs a verified SQLite backup before Git mutation, fetches only the selected tag, pins Stable to the exact target commit, runs target Prepare + Validate, and stops.

It never chooses `latest`, follows `main`, starts Hermes, runs DB migration, updates Preview, publishes a release/tag or performs automatic rollback.

### Acceptance boundary

The implementation/CI/review are complete, but the **first real owner Stable release-to-release UAT is still pending** because no newer real Stable release has been published after OPS02 landed.

Do not publish a throwaway release just to exercise the updater.

The first real proof should be:

`v0.8.2 → next genuine published immutable Stable release`.

Issue #313 therefore stays open.

## Release publication

Release publication is separate from updating the local Stable runtime.

Permanent guarded owner-control endpoint: issue #124.

The chat-first guarded release flow is documented in [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md).

A release publishes an immutable tag/GitHub Release from exact canonical `main`; it does not automatically mutate production Stable.

## Current product surfaces

The current development product includes the published 0.8.2 capabilities plus post-release integrated work such as:

- Scenario Lab v1;
- financial-context completeness / plan-vs-fact data;
- Performance v1 (XIRR/TWRR/PERF04A);
- linked asset/card financing integrity and AI-review hardening;
- prepared runtime + deterministic Start;
- explicit immutable Stable update operation;
- PERF04C exact account + internal-transfer decomposition backend read model;
- ongoing reversible UI v2 work under a separate roadmap while v1 remains available.

For the authoritative current snapshot use `docs/CURRENT_STATUS.md` rather than inferring release state from old milestone docs.

## What comes next

UI v2 is tracked independently through #387 and its children.

For the non-UI runtime stream, the next bounded direction under #313 is **exact Preview/UAT preparation pinned to one explicit candidate SHA** so owner UAT cannot silently move when `main` advances.

For Performance, exact account decomposition is implemented; instrument/asset-class attribution still requires a separately accepted data/evidence foundation before implementation.

The next real Stable release will also be the first opportunity for mandatory OPS02 owner transition UAT.

## Health

After a successful local start:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Open Hermes:

```text
http://127.0.0.1:8000
```

## Development checks

Use the repository verification policy rather than inventing ad-hoc acceptance gates:

- `AGENTS.md`;
- [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md);
- task-specific accepted issue/contract.

Canonical PR CI and exact-main push CI are mandatory for integrated changes.

## Documentation map

- [`AGENTS.md`](AGENTS.md) — project constitution and execution rules;
- [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — business rules / core product semantics;
- [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md) — current canonical checkpoint;
- [`docs/PROJECT_WIKI.md`](docs/PROJECT_WIKI.md) — durable current project context;
- [`docs/OWNER_RUNTIME_OPERATIONS.md`](docs/OWNER_RUNTIME_OPERATIONS.md) — launcher/runtime owner operations;
- [`docs/EXECUTION_HISTORY.md`](docs/EXECUTION_HISTORY.md) — durable execution journal;
- [`docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`](docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md) — Performance v1 closeout;
- [`docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`](docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md) — current component-decomposition contract;
- [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md) — guarded release publication;
- [`CHANGELOG.md`](CHANGELOG.md) — release/development change log.

## Privacy

Never commit or expose:

- real `.env`;
- production or Preview/UAT databases;
- SQLite sidecars/backups;
- provider tokens/credentials;
- private owner exports/PDF payloads;
- reconstructive personal financial datasets.

Use synthetic fixtures for development and CI.
