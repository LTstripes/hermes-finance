# Hermes Finance

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Оно помогает закрывать месяц, видеть ликвидный капитал и долги, анализировать инвестиционный результат и пассивный доход, работать с целями/Tax/IIS/Scenario Lab, проверять reconciliation/freshness и экспортировать read-only AI Analysis Bundle.

## Current status

Published release is **v1.2.0** at `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; annotated tag object `f9311d26c1aae7295361937096844f4dde615b55` peels to that exact commit. Canonical CI `37206069556` and Guarded Release `37206660242` succeeded. Last locally confirmed Stable is v1.1.0; the authorized backup-first update to 1.2.0 has not been reported complete here. [Release record](docs/releases/1.2.0.md).

**Development code milestone:** `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4` (merge #701), exact-main CI `37226437369` SUCCESS. Class-return Phase 1 (#696/#698/#535/#540) is integrated on main **after v1.2.0**, not in that published release or automatically installed in Stable/Test. Live GitHub remains authoritative; later documentation commits may advance main.

#572 is CLOSED with **Owner PASS WITH DOCUMENTED LIMITATIONS**, including manual/v1 use and provider limitations. The earlier deferral is historical, superseded by [actual acceptance](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5937693786), not retroactively relabelled PASS. UI v2 is primary at `/`; `/v1` remains available.

v1.2.0 includes the accepted #662 post-v1.1.0 product wave, #667/#674, CI optimization #668–#671 and repository Launcher retirement #629. #646 remains a separate Alfa compatibility limitation. #679/#666 migration/legacy cleanup and #685 janitor deployment are complete; [machine layout](docs/OWNER_MACHINE_LAYOUT.md) protects the separate active Ops installation.

Current detail: [CURRENT_STATUS](docs/CURRENT_STATUS.md). Restart brief: [SESSION_CLOSEOUT_2026-10-04](docs/SESSION_CLOSEOUT_2026-10-04.md).

## Product/runtime invariants

- Windows 10/11, single user, local SQLite; normal endpoint `127.0.0.1:8000`.
- No cloud account, auth, telemetry, trading or background provider refresh. Provider/network reads require explicit Owner actions.
- Production/Test data, .env, backups, credentials and private exports never enter development workspaces or CI.
- CLOSED months are immutable until explicit Reopen. Backend/domain is the financial source of truth.
- Exact money uses Decimal / integer minor units. Unknown/unavailable is not zero.
- Housekeeping does not refresh providers, change financial data or promote releases.

## Major completed lines

### Monthly Close / UI v2

Native month/editor operations, explicit imports/Preview/Apply/readback, exact-month final review/report/Reopen, Goals/Tax/IIS/Scenario and data/application tools are integrated. Home, Capital, Income and Plans, contextual History/Reports and Monthly Close are primary v2 surfaces. `/v1` and retained deep links remain intentional; #573 is CLOSED / NOT_PLANNED unless Owner revisits retirement.

The accepted product wave adds exact-month navigation, saved-only reread, Settings/Diagnostics, collapsed bulk/individual future payouts, contextual verified mapping, exception-first Alfa, money/debt readability and linked-pair explanation. Lifecycle/financial boundaries are unchanged.

Evidence: [UI completion](docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md), [default switch](docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md), [post-release UAT](docs/POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md).

### Decision Support v1

AI Analysis Bundle, Monthly Close Cockpit, Cash-flow Ladder, Risk & Allocation, Freshness & Provenance, Reconciliation, current-state Tax/IIS, deterministic Insights and Scenario Lab are integrated. Scenario Lab is deterministic/read-only, not a market forecast. AI export `schema_version=1.3.0` is independent of the application release.

Closeout: [Decision Support v1](docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md).

### Performance and data integrity

Portfolio/account XIRR, exact TWRR, flow/valuation/membership/transfer/in-kind safeguards, diagnostics/preparation and PERF04A monetary bridge are delivered.

**Class-return Phase 1 is integrated in development main.** The existing Performance detail now has Accounts/Classes, exact-date presets and independent annualized XIRR / period TWRR. Stock/bond/gold require historical C1 identity, explicit no-crossing coverage, both full endpoint inventory claims and exact persisted RUB valuations. Deposits are visibly unsupported. Evidence gaps and numerical limitations remain distinct.

This first slice does not import purchases/sales/distributions, implement flow-bearing class TWRR/FX, or provide a class-attestation input form. Legacy C1 remains unknown, not backfilled. The read-only class table does not imply that personal history already has computable percentages. [Class contract](docs/performance/ASSET_CLASS_RETURNS_CONTRACT.md), [endpoint evidence](docs/performance/CLASS_NO_CROSSING_ENDPOINTS.md), [API](docs/performance/CLASS_RETURNS_API.md).

`value_change_after_external_flows` is not return/profit/P&L. The backend-only decomposition `B_portfolio = Σ B_account + Σ T_internal_transfer` has no residual bucket or partial exact split. Class return does not implement additive class attribution, price/FX decomposition or cost-basis accounting. [PERF04B contract](docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md).

Data-integrity #484–#498/#536–#539 and #621–#624 preserve atomic writes, coherent SQLite reads, source coverage and stale-evidence invalidation. Missing accounts/periods are not zero-filled. [Performance v1](docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md), [integrity closeout](docs/DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

### Recovery and durability

#417 is complete: explicit recovery-point publication/read-back, bounded retention, isolated DR, post-restore reload and truthful ambiguous outcomes. Encrypted and separately Owner-accepted plaintext synced-filesystem modes remain distinct. A synchronized folder is not automatically encrypted or proven off-device. #543/PR #547 completed separate CLI/retention hardening.

Evidence and commands: [durability closeout](docs/OWNER_DURABILITY_CLOSEOUT_2026-09-25.md), [runtime operations](docs/OWNER_RUNTIME_OPERATIONS.md).

## Requirements

- Windows 10/11;
- Python 3.13 and [uv](https://docs.astral.sh/uv/);
- Node.js **22.23.1** (tested/recommended, `frontend/.nvmrc`) and npm; permitted versions are declared in `frontend/package.json`, with `.npmrc` enforcement;
- modern browser.

Docker/PostgreSQL/public web hosting are not required.

## Development installation

From an isolated development checkout, never production Stable:

```powershell
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
```

Dependencies remain locked by `backend/uv.lock` and `frontend/package-lock.json`. Clients create task copies below their configured roots; see [AGENTS](AGENTS.md).

## Windows launcher — retired

The Launcher GUI/package/install/tests/jobs were retired by #629 after Owner-local removal during #679. **Do not reinstall it to run Hermes or repair layout.** Direct Prepare/Validate/Start is the supported route. Shared `launcher-production-backup.py` through `update-stable-lib.ps1`, prepared-runtime, recovery and RuntimeConfig protections remain even where a helper name is historical.

Recovery/cleanup exclusions use the direct-operations inventory: [OWNER_RUNTIME_OPERATIONS §13](docs/OWNER_RUNTIME_OPERATIONS.md#13-protected-off-site-recovery-points-and-dr-rehearsal), [example](docs/runtime-inventory.example.json). Earlier shell/self-updater work is historical: [R09](docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md).

## Explicit Prepare + deterministic Start

From the exact selected runtime checkout:

```powershell
$checkout = (Get-Location).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout -Prepare
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $checkout -Validate
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Readiness smoke:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

Prepare installs locked dependencies, builds the frontend and records ignored exact-build proof. Start validates it without silently installing/building or moving refs. Re-prepare a relocated Windows Python environment rather than reusing old absolute interpreter entry points. Never change production DB binding to bypass startup failure.

## Explicit Stable release update

Run OPS02 from trusted Main/Control, outside mutable Stable:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

It proves a published annotated release, makes a verified SQLite backup before Git mutation, pins the exact target, runs Prepare + Validate and stops. It never chooses latest, follows main, starts Hermes, updates Test, publishes a release, runs DB migration or automatically rolls back/downgrades.

## Exact Preview/UAT preparation

Use persistent Test with isolated data and an explicit candidate:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-preview.ps1 `
  -CandidateSha <full-40-char-sha> `
  -PreviewCheckout <test-checkout-path> `
  -PreviewDataDirectory <isolated-test-data-path> `
  -PreviewDatabase <isolated-test-db-path> `
  -StableCheckout <stable-path> `
  -StableDataDirectory <stable-data-path> `
  -StableDatabase <stable-db-path> `
  -ControlCheckout <main-checkout-path>
```

Existing-path guards remain authoritative. Reuse the role/location, not an unsafe overwrite. Stop the owned runtime before changing its checkout; only one runtime owns port 8000. Operational preparation belongs to an explicitly authorized local Worker. [Runtime operations](docs/OWNER_RUNTIME_OPERATIONS.md).

## Release publication

Publication is separate from installation. Permanent guarded Owner endpoint: **#124**; see [RELEASE_AUTOMATION](docs/RELEASE_AUTOMATION.md).

The normal sequence remains exact-SHA isolated UAT → Owner acceptance → guarded publication → explicit backup-first OPS02 → Start and continuity verification. Release-specific Owner decisions are recorded in their release record; they are not standing waivers for future versions. No release follows automatically from a merged PR or folder move.

## What comes next

- **#702 read-only statement-backed class-event research** is selected and can run independently of Owner UAT. Its output is a proposed contract/source matrix and ordered implementation slices, not code delivery.
- Owner plans UAT tomorrow or in the following days. Class-return testing needs an explicitly prepared post-#701 candidate: published v1.2.0 does not contain it. No UAT PASS or local deployment is implied. The missing class-attestation/legacy-identity UI remains a product gap; do not assign Owner database/JSON/PowerShell workarounds.
- #646 Alfa remains a known limitation: Trading core UI Online on 3366 and read-only token issued, but Hermes reports unrecognized protocol. No new token/handshake contract is proven. Owner elected to wait several days/about a week before support. This does not block statement research.
- #389 composer is deferred. #630/#573/#127 are closed not-planned; #528/#541 are closed coordination. `/v1` stays.
- CI/test optimization #668–#671/#629 is complete; #691 was NO-GO with no delivered change. [CI/test closeout](docs/history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md).
- Migration/janitor setup #679/#666 is complete. Preserve the active separate Ops installation; [janitor rules](docs/WORKSPACE_JANITOR.md) do not grant arbitrary deletion.

## Health

After a successful local start:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Published v1.2.0 reports `status=ok`, `version=1.2.0` after actual local update. Health version alone does not prove a later development SHA; check exact Git/runtime identity for post-release UAT. Open `http://127.0.0.1:8000`.

## Documentation map

- [AGENTS](AGENTS.md), [verification](docs/VERIFICATION_POLICY.md), [routing](docs/MODEL_ROUTING.md): authority and proportional procedures. Worker prompts normally stay 5–10 lines and reference the task instead of duplicating it.
- [MASTER_SPEC](docs/MASTER_SPEC.md), accepted ADRs and linked task contracts: product semantics.
- [CURRENT_STATUS](docs/CURRENT_STATUS.md), [PROJECT_WIKI](docs/PROJECT_WIKI.md), [latest closeout](docs/SESSION_CLOSEOUT_2026-10-04.md): active state and restart brief.
- [Layout](docs/OWNER_MACHINE_LAYOUT.md), [runtime operations](docs/OWNER_RUNTIME_OPERATIONS.md), [janitor](docs/WORKSPACE_JANITOR.md): folders and direct operations.
- [EXECUTION_HISTORY](docs/EXECUTION_HISTORY.md) and dated closeouts preserve history; old model attribution is not reporting policy.
- [v1.2.0 record](docs/releases/1.2.0.md), [v1.2.0 notes](docs/release-notes-1.2.0.md), [v1.1.0 record](docs/releases/1.1.0.md): release-era evidence, not instructions to repeat completed work.

## Privacy

Never commit real .env, production/Test DBs, SQLite sidecars/backups, provider credentials, private exports/PDFs or reconstructive personal datasets. Development/CI use synthetic fixtures. Normal model handoffs do not request or record runtime model/provider identity or benchmarks.
