# Hermes Finance

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Оно помогает закрывать месяц, видеть ликвидный капитал и долги, анализировать инвестиционный результат и пассивный доход, работать с целями/Tax/IIS/Scenario Lab, проверять reconciliation/freshness и экспортировать read-only AI Analysis Bundle.

## Current status

Published Stable: **v0.9.0** (2026-09-17).

- released/UAT code identity: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`;
- annotated tag object: `07c06d44f8b780e721be346a21909ca02585d57d`;
- guarded Release #253 / run `35235369797`: SUCCESS;
- exact-main release-gate CI #700 / run `35207551120`: SUCCESS;
- latest product/runtime integration checkpoint before this documentation sync: `583f9167ae14509202ef47978e7b9f20180e188d` — controlled UI v2 default switch;
- exact-main CI for that checkpoint: #872 / run `35573224359`: SUCCESS;
- live development SHA is always the current GitHub `main`; docs-only synchronization commits may advance it;
- restore-outcome safety #475 merged immediately before cutover at `a11c1b3580ffa2dad0b6bd7f19fe6d2dae2e6fba`, exact-main CI #869 / `35571951532`: SUCCESS;
- current development truth: canonical GitHub `main` + [CURRENT_STATUS](docs/CURRENT_STATUS.md);
- UI v2 is now the primary/default owner interface; v1 remains available at `/v1` as an explicit rollback/legacy home.

Owner release acceptance is complete:

- OPS03 exact-SHA Preview/UAT on `c90a842...`: **PASS**;
- real OPS02 Stable transition `v0.8.2 -> v0.9.0`: **PASS**;
- production v0.9.0 readiness smoke: **PASS**;
- `/api/health`: `0.9.0`;
- owner data continuity: **PASS**.

Detailed checkpoint: [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md).
Runtime/release closeout: [`docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`](docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md).

Prepared release candidate: **v1.0.0** — `PREPARED / UAT-PENDING` under #480.

- published Stable remains `v0.9.0`;
- no `v1.0.0` tag or GitHub Release exists yet;
- the candidate packages the accepted UI v2 default switch, restore-outcome safety and other accepted post-v0.9.0 work already on canonical development `main`;
- next gate after release-prep integration is one exact-SHA OPS03 Preview/UAT; only Owner PASS permits guarded publication and the real backup-first Stable transition `v0.9.0 -> v1.0.0`.

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

### Protected recovery-point publisher

#459 / PR #466 is accepted and integrated on canonical `main`.

- accepted candidate: `8eb47bb1261861354bf1dbec1271cc538f4b1bc4`;
- canonical merge: `49144da863c93e5afc505e16be6817c55ff2b50d`;
- independent security/recovery review: ACCEPT;
- exact-main CI #839 / run `35518134142`: SUCCESS;
- supported mode is provider-neutral `external_encrypted_destination_v1` over an explicitly attested mounted filesystem destination;
- no cloud API/OAuth, custom cryptography, key validation, retention deletion, DR rehearsal or Owner-live backup was added by #459.

The durability queue continues with #460 retention, #461 isolated DR rehearsal and #462 restore-state reload. Real protected off-device use remains Owner-controlled.

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

The launcher is a quiet owner-facing shell for configured, already-prepared Stable and isolated Main/Preview profiles:

- profile/status presentation;
- ordinary Start/Stop;
- open Hermes after health is ready;
- diagnostics;
- installed Desktop/Start-menu shortcuts.

It shows exact version/SHA identity, readiness and the production/isolated data boundary. Its ordinary Start and status refresh are read-only with respect to Git and release state: it never follows `origin/main`, fetches, switches refs, publishes releases or performs OPS02/OPS03 work. Dependency readiness is read-only in the launcher; run external OPS01 Prepare when needed, then use Start, Stop, Open Hermes, setup and secondary diagnostics/logs.

Stable release transition remains `scripts/update-stable.ps1`; exact Preview/UAT preparation remains `scripts/prepare-preview.ps1`. These composable operations are intentionally outside the launcher.

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

Published `v0.9.0` remains the current Stable release. Development `main` has advanced beyond that immutable release with accepted post-release work.

UI v2 is **not part of the published v0.9.0 release**, but it is now the primary/default owner interface on development `main`.

Final UI v2 cutover evidence:

- completion aggregate Owner-UAT SHA: `edd6a32d94ba322badaea1cab804c4e5cc13574d` — PASS;
- completion aggregate PR #455 / canonical merge `424ba7bf018c8e4ac01cfda825af7394a3068267`;
- controlled default-switch frozen Owner-UAT SHA: `09649bb1d71d6bdff636bb6becbf16d9f0cd5083` — PASS;
- default-switch PR #474 / canonical merge `583f9167ae14509202ef47978e7b9f20180e188d`;
- exact-main CI #872 / run `35573224359`: SUCCESS;
- route contract: `/` -> UI v2, `/v1` -> previous UI Dashboard, existing legacy deep links/editors remain available.

Native UI v2 includes:

- «Мои финансы» Home;
- Capital;
- «Доход и планы»;
- contextual Reports/history;
- native Monthly Close over the authoritative server workflow;
- full «Данные и приложение»:
  - sources/freshness/provenance;
  - explicit read-only reconciliation;
  - catalogs + persistent mappings;
  - exports + safety-gated local backup/restore;
  - application settings + tax brackets + runtime diagnostics;
- global «Наверх» behavior for long pages;
- final owner-facing Russian terminology/copy cleanup;
- accepted Expected payouts hierarchy/alignment, Reports spacing and Reconciliation copy polish.

Immediately before final cutover, #475 hardened restore-result truthfulness: confirmed negative outcomes remain distinct from `restore_outcome_ambiguous`, ambiguous outcomes refresh shared reads and are never blindly retried. Independent safety re-review passed before merge.

Closeouts:

- [`docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md`](docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md) — implementation/completion milestone;
- [`docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md`](docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md) — final comparative audit, safety reconciliation, Owner UAT and controlled default switch.

## What comes next

The **core UI v2 roadmap (#387) is complete**.

There is no remaining default-switch gate. UI v2 is primary at `/`; v1 remains available at `/v1` and through retained legacy editor/deep-link routes.

Separate future work:

- #476 — one real-backend synthetic G04 browser regression gate; this is regression infrastructure, not a blocker to the accepted cutover;
- #460/#461/#462 — remaining durability/DR/legacy restore-state work under #417;
- v1 retirement — only if later real use shows the rollback/legacy layer is no longer needed, via a separate explicit task;
- future configurable dashboards (#389) remain separate from the completed core UI v2 roadmap.

Release publication/runtime promotion remains separate from development-main acceptance. The prepared `v1.0.0` candidate is tracked in #480; after exact-SHA OPS03 Owner PASS it may be published through #124 and then installed into real Stable through backup-first OPS02.

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

The prepared `v1.0.0` candidate, when run in isolated OPS03 Preview/UAT, must instead report:

```json
{
  "status": "ok",
  "version": "1.0.0"
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
- [`docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md`](docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md) — UI v2 implementation/completion closeout;
- [`docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md`](docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md) — final UI v2 default-switch/Owner-UAT closeout;
- [`docs/EXECUTION_HISTORY.md`](docs/EXECUTION_HISTORY.md) — durable execution journal;
- [`docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`](docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md) — Performance v1 closeout;
- [`docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`](docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md) — component-decomposition contract;
- [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md) — guarded release publication;
- [`docs/release-notes-1.0.0.md`](docs/release-notes-1.0.0.md) — prepared v1.0.0 public release notes;
- [`docs/releases/1.0.0.md`](docs/releases/1.0.0.md) — prepared/UAT-pending v1.0.0 release record;
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
