# Hermes Finance

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Оно помогает закрывать месяц, видеть ликвидный капитал и долги, анализировать инвестиционный результат и пассивный доход, работать с целями/Tax/IIS/Scenario Lab, проверять reconciliation/freshness и экспортировать read-only AI Analysis Bundle.

## Current status

Published Stable: **v0.9.0** (2026-09-17).

- released/UAT code identity: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`;
- annotated tag object: `07c06d44f8b780e721be346a21909ca02585d57d`;
- guarded Release #253 / run `35235369797`: SUCCESS;
- exact-main release-gate CI #700 / run `35207551120`: SUCCESS.

Owner release acceptance is complete:

- OPS03 exact-SHA Preview/UAT on `c90a842...`: **PASS**;
- real OPS02 Stable transition `v0.8.2 -> v0.9.0`: **PASS**;
- production v0.9.0 readiness smoke: **PASS**;
- `/api/health`: `0.9.0`;
- owner data continuity: **PASS**.

Detailed checkpoint: [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md).
Runtime/release closeout: [`docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`](docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md).

Known non-blocking metadata follow-up: #410 corrects stale candidate wording in the GitHub Release description; published tag/code identity is unaffected.

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

#400 / PR #402 implemented the bounded backend read model.

Important boundaries:

- no partial split or residual bucket;
- instrument/asset-class, price-vs-FX, realised/unrealised and lot/cost-basis attribution remain unsupported from current evidence;
- unknown evidence remains unavailable/null rather than estimated.

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

The launcher is **not retired**, and it intentionally still looks/behaves familiar for ordinary owner use.

Its proven role is the owner-facing shell for the configured Stable/Preview profiles:

- profile/status presentation;
- ordinary Start/Stop;
- open Hermes after health is ready;
- diagnostics;
- installed Desktop/Start-menu shortcuts.

The historical launcher-owned Stable self-update experiment (#298/#311/#312) is **not** the canonical update path.

The important v0.9.0 improvement is architectural: release mutation, Preview/UAT preparation, runtime preparation and Start are separate accepted operations instead of one launcher-owned state machine.

To install/reinstall the launcher from the current published Stable checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\windows\install.ps1
```

Detailed owner operations: [`docs/OWNER_RUNTIME_OPERATIONS.md`](docs/OWNER_RUNTIME_OPERATIONS.md).

## Explicit Prepare + deterministic Start

OPS01 separates preparation from ordinary Start.

Prepare:

```powershell
$checkout = (Get-Location).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Prepare
```

Validate:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout `
  -Validate
```

Start:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Short readiness smoke:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

Prepare installs only required locked dependencies, builds the production frontend and records ignored exact-build proof. Start validates that proof and does not silently build, install dependencies or move Git refs.

## Explicit Stable release update — owner proven

OPS02 (#386 / PR #393) is the canonical Stable release transition operation.

Run it from a trusted **control checkout outside mutable Stable**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

The operation proves the published annotated target, performs a verified SQLite backup before Git mutation, fetches only the selected tag, pins Stable to the exact peeled target commit, runs target Prepare + Validate, and stops.

It never chooses `latest`, follows `main`, starts Hermes, runs DB migration, updates Preview, publishes a release/tag or performs automatic rollback.

The first real owner transition `v0.8.2 -> v0.9.0` passed on 2026-09-17, including exact target pinning and proof that the production DB did not change during update before explicit Start.

## Exact Preview/UAT preparation — owner proven

OPS03 (#404 / PR #407) prepares an isolated independent Preview pinned to one explicit full SHA:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-preview.ps1 `
  -CandidateSha <full-40-char-sha> `
  -PreviewCheckout <preview-path> `
  -PreviewDataDirectory <isolated-data-path> `
  -PreviewDatabase <isolated-db-path> `
  -StableCheckout <stable-path> `
  -StableDataDirectory <stable-data-path> `
  -StableDatabase <stable-db-path>
```

The first real release UAT pinned Preview exactly to the `v0.9.0` release code and passed against isolated owner-controlled data before publication.

## Release publication

Release publication is separate from updating local Stable.

Permanent guarded owner-control endpoint: issue #124.

The chat-first guarded release flow is documented in [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md).

The proven sequence is now:

1. exact-SHA owner Preview/UAT;
2. guarded immutable release publication;
3. explicit OPS02 Stable transition;
4. explicit production Start + health/data-continuity verification.

`v0.9.0` is the first release to complete the full chain successfully.

## Current product surfaces

Published `v0.9.0` includes:

- Scenario Lab v1;
- financial-context completeness / plan-vs-fact data;
- Performance v1 (XIRR/TWRR/PERF04A);
- linked asset/card financing integrity and AI-review hardening;
- deterministic Prepare + Start;
- explicit immutable Stable update;
- exact-SHA isolated Preview/UAT preparation;
- PERF04C exact account + internal-transfer decomposition backend read model.

UI v2 remains a separate workstream and is **not** part of `v0.9.0`.

## What comes next

UI v2 is tracked independently through #387 and its children. The temporary `v0.9.0` release freeze can be lifted after the successful publication + Stable UAT.

The runtime redesign parent #313 is complete after the first real OPS02 owner transition. Further diagnosis/recovery or launcher wrappers should be separate bounded tasks, not extensions of the old update state machine.

For Performance, instrument/asset-class exact attribution still requires a separately accepted data/evidence foundation.

`1.0.0` remains a reasonable future milestone only after a cohesive UI v2 owner experience and the production lifecycle are both accepted.

## Health

After a successful local start:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Current Stable should include:

```json
{
  "status": "ok",
  "version": "0.9.0"
}
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

Canonical PR CI and exact-main push CI remain mandatory for integrated changes.

## Documentation map

- [`AGENTS.md`](AGENTS.md) — project constitution and execution rules;
- [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — business rules / core product semantics;
- [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md) — current canonical checkpoint;
- [`docs/PROJECT_WIKI.md`](docs/PROJECT_WIKI.md) — durable current project context;
- [`docs/OWNER_RUNTIME_OPERATIONS.md`](docs/OWNER_RUNTIME_OPERATIONS.md) — launcher/runtime owner operations;
- [`docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`](docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md) — proven runtime/release closeout;
- [`docs/EXECUTION_HISTORY.md`](docs/EXECUTION_HISTORY.md) — durable execution journal;
- [`docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`](docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md) — Performance v1 closeout;
- [`docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`](docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md) — component-decomposition contract;
- [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md) — guarded release publication;
- [`docs/release-notes-0.9.0.md`](docs/release-notes-0.9.0.md) — final v0.9.0 notes;
- [`docs/releases/0.9.0.md`](docs/releases/0.9.0.md) — published v0.9.0 release record.

## Privacy

Never commit or expose:

- real `.env`;
- production or Preview/UAT databases;
- SQLite sidecars/backups;
- provider tokens/credentials;
- private owner exports/PDF payloads;
- reconstructive personal financial datasets.

Use synthetic fixtures for development and CI.
