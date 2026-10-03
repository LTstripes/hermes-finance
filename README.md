# Hermes Finance

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Оно помогает закрывать месяц, видеть ликвидный капитал и долги, анализировать инвестиционный результат и пассивный доход, работать с целями/Tax/IIS/Scenario Lab, проверять reconciliation/freshness и экспортировать read-only AI Analysis Bundle.

## Current status

Published Stable: **v1.1.0** (2026-09-30).

- released commit: `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`, release tree `7f5a3198fa650b71545550301063c9afd887f8f8`;
- annotated tag `v1.1.0`, tag object `9b402190bafc5d8415b217580da5e18ed35a6331`, peeling exactly to the released commit;
- GitHub Release `Hermes Finance 1.1.0`: published, not a draft or prerelease;
- release preparation PR #644, accepted head `f4de8e39217ee0ec73b2524433940674247461f7`; exact-main push CI `36776904188`: SUCCESS; guarded Release run `36777962224`: SUCCESS;
- release control: [issue #643](https://github.com/LTstripes/hermes-finance/issues/643);
- local Stable update/Start and real-history acceptance remain explicit Owner operations; publication does not itself update or start Stable. See the [1.1.0 release record](docs/releases/1.1.0.md);
- UI v2 is the primary/default interface at `/`; previous UI remains available at `/v1`.

Owner-authorized UAT deferral for this delivery is **OWNER_AUTHORIZED_UAT_DEFERRAL**, not Owner PASS; [#572](https://github.com/LTstripes/hermes-finance/issues/572) stays open for the ordinary production-use observation.

The previous release **v1.0.0** (2026-09-21) remains immutable predecessor history:

- released / Owner-OPS03-tested code identity: `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`;
- annotated tag object: `f99ee8ecac1acde7f559d92ee8f45ddcfcdfaa47`, peeling exactly to that commit;
- guarded Release run `35580890145`: SUCCESS; exact-main release-candidate CI #880 / run `35579583692`: SUCCESS;
- Owner OPS03 Preview/UAT on that exact code: **PASS**; real backup-first OPS02 Stable transition `v0.9.0 -> v1.0.0`: **PASS**; production Stable Start / owner data continuity: **PASS**.

The immutable published `v0.9.0` history remains valid as the predecessor to v1.0.0.

Canonical status: [CURRENT_STATUS](docs/CURRENT_STATUS.md).
v1.1.0 record: [`docs/releases/1.1.0.md`](docs/releases/1.1.0.md).
v1.1.0 publication notes: [`docs/release-notes-1.1.0.md`](docs/release-notes-1.1.0.md).
v1.0.0 release closeout: [`docs/R10_RELEASE_CLOSEOUT_2026-09-21.md`](docs/R10_RELEASE_CLOSEOUT_2026-09-21.md).
Owner durability closeout: [`docs/OWNER_DURABILITY_CLOSEOUT_2026-09-25.md`](docs/OWNER_DURABILITY_CLOSEOUT_2026-09-25.md).

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

### Post-release data-integrity hardening

The Astra-audit hardening wave is complete on development `main`:

- atomic financial writes and closed-month race protection;
- coherent composite SQLite reads;
- safe statement/payout/transfer/salary/month-clone concurrency handling;
- stale Performance evidence invalidation/version binding;
- preserved real/unassigned cash identity through AI/export;
- canonical portfolio-source completeness from backend through AI reviews and owner UI, without zero-filling missing accounts.

All scoped issues #484–#498 and #536–#539 are closed. Aggregate PR #509 merged as canonical `main` `b6f3ff1aff93f06ae0a563ba8704b91086a80924`; exact-main push CI `36306845860` succeeded.

Closeout: [`docs/DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md`](docs/DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

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

#460 bounded verified retention, #461 isolated DR rehearsal and #462 post-restore month-state reload are now integrated on canonical `main`. The #461 implementation required post-merge Windows process-disposition fix PR #499; #462 then closed the retained Export/Backup stale-month race. Final implementation checkpoint `5bb52b8e1a8394e389968514deaeb4faf8cc5a19` passed exact-main CI #904 / `35771083594`. The #417 implementation queue through #462 is complete.

#527 / PR #542 added the explicit Owner-accepted plaintext synced-filesystem mode: `protection_state=owner_accepted_plaintext`, `protection_mode=synced_filesystem_destination_v1`. It is not encrypted or protected-at-rest; the existing `external_encrypted_destination_v1` mode remains unchanged. Canonical durability checkpoint `744c613884d074e6f9d35d61523603f257371713` passed exact-main CI #947 / `36139627216`. Owner-live closeout then passed: a fresh plaintext recovery point was published with destination read-back verified, its off-device visibility was confirmed independently, and a clean isolated DR rehearsal returned `status=rehearsed`, `readiness=verified`, `source_unchanged=true`. Parent #417 is closed completed. #543 / PR #547 then completed the separate non-blocking CLI/retention hardening without reopening #417.

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

The launcher is now a compact owner shell for configured, already-prepared Stable and isolated Preview profiles. The normal window is intentionally small: choose the environment, see one concise version/SHA + data-boundary line, see one readiness state, and use one primary action for that state.

Normal actions are:

- `Готов` → `Запустить`;
- `Работает` → `Открыть Hermes`;
- launcher-owned running process → secondary `Остановить`;
- blocked / needs preparation → one contextual recheck action;
- diagnostics/logs stay hidden until requested;
- `Настроить…` is recovery/setup, not the ordinary daily path.

The launcher remains read-only with respect to Git/release state: it never follows `origin/main`, fetches, switches refs, publishes releases or performs OPS02/OPS03 work. Stable release transition remains `scripts/update-stable.ps1`; exact Preview/UAT preparation remains `scripts/prepare-preview.ps1`.

The heavy Windows launcher safety + package/install CI lane is path-gated since #585: unrelated frontend/financial/backend changes skip that lane, while launcher/package/schema-helper changes still run the full retained safety harness.

To install/reinstall the **released** launcher, run `install.ps1` from the published Stable checkout. To try the newer launcher currently on development `main` before the next Stable release, run the same installer from a clean current-main/control checkout; this updates only the installed launcher package/shortcuts and does not promote or mutate the Stable runtime/database.

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

Published **v1.1.0** is the current release. The accepted native monthly workflow, Performance Phase A, and the post-1.0.0 durability and data-integrity/completeness hardening it packages are described below.

UI v2 is part of the published v1.1.0 release and is the primary/default owner interface at `/`; the previous UI remains available at `/v1`.

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

- #476 / PR #548 is complete: canonical CI now runs one deterministic synthetic real-backend G04 owner journey;
- #417 owner durability remains complete; #543 / PR #547 separately completed the non-blocking recovery CLI/retention hardening without reopening it;
- v1 retirement — only if later real use shows the rollback/legacy layer is no longer needed, via a separate explicit task;
- future configurable dashboards (#389) remain separate from the completed core UI v2 roadmap.

Release publication for v1.1.0 is complete. The supported backup-first Stable update (`scripts/update-stable.ps1 -TargetVersion 1.1.0`) and explicit Start remain the Owner's local operation; publication does not itself update or start Stable. Future releases continue to use the same exact-SHA OPS03 -> guarded publication -> backup-first OPS02 sequence.

## Health

After a successful local start:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

The published v1.1.0 application reports:

```json
{
  "status": "ok",
  "version": "1.1.0"
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
- [`docs/DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md`](docs/DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md) — Astra-audit data-integrity/completeness closeout;
- [`docs/EXECUTION_HISTORY.md`](docs/EXECUTION_HISTORY.md) — durable execution journal;
- [`docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`](docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md) — Performance v1 closeout;
- [`docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`](docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md) — component-decomposition contract;
- [`docs/RELEASE_AUTOMATION.md`](docs/RELEASE_AUTOMATION.md) — guarded release publication;
- [`docs/release-notes-1.1.0.md`](docs/release-notes-1.1.0.md) — v1.1.0 release notes;
- [`docs/releases/1.1.0.md`](docs/releases/1.1.0.md) — v1.1.0 release record;
- [`docs/release-notes-1.0.0.md`](docs/release-notes-1.0.0.md) — final v1.0.0 release notes;
- [`docs/releases/1.0.0.md`](docs/releases/1.0.0.md) — published v1.0.0 release record;
- [`docs/R10_RELEASE_CLOSEOUT_2026-09-21.md`](docs/R10_RELEASE_CLOSEOUT_2026-09-21.md) — v1.0.0 publication/Stable closeout;
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
