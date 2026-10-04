# Hermes Finance

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Оно помогает закрывать месяц, видеть ликвидный капитал и долги, анализировать инвестиционный результат и пассивный доход, работать с целями/Tax/IIS/Scenario Lab, проверять reconciliation/freshness и экспортировать read-only AI Analysis Bundle.

## Current status

Published release is **v1.2.0** at `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; annotated tag object `f9311d26c1aae7295361937096844f4dde615b55` peels to that exact commit. Canonical CI `37206069556` is SUCCESS after a single failed G04 job was retried in isolation and passed; Guarded Release `37206660242` succeeded. The last locally confirmed Stable is still v1.1.0 until the Owner performs backup-first OPS02 to 1.2.0. [Release record](docs/releases/1.2.0.md).

#572 is CLOSED with **Owner PASS WITH DOCUMENTED LIMITATIONS**, including manual/v1 use and provider limitations. The earlier pre-publication deferral is historical, superseded by [actual Owner acceptance](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5937693786), not retroactively relabelled as an earlier PASS. UI v2 is primary at `/`; the previous UI stays at `/v1`.

**v1.2.0 now contains the accepted post-v1.1.0 product wave and maintenance line.** #662 plus #667/#674, CI/test optimization #668–#671 and repository Launcher retirement #629 are in the published release. #646 remains a separate Alfa PRO compatibility limitation and is not claimed fixed by publication.

**Filesystem migration is complete:** #679/#666 moved Stable/Main/persistent Test, removed the authorized legacy forest and deployed daily workspace cleanup through #685. Installed Launcher/config/shortcuts were removed and repository Launcher source/package/tests/workflows are retired by #629. The [machine-layout contract](docs/OWNER_MACHINE_LAYOUT.md) also protects the separate active Ops installation; outside the Hermes root does not automatically mean disposable.

Release checkpoint: `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; exact-main CI `37206069556` SUCCESS, Guarded Release `37206660242` SUCCESS. Any later main movement from release closeout docs does not change the immutable v1.2.0 tag. Live GitHub remains authoritative. See [CURRENT_STATUS](docs/CURRENT_STATUS.md) and [v1.2.0 release record](docs/releases/1.2.0.md).

## Product/runtime invariants

- Windows 10/11, single user, local-only, local SQLite; normal endpoint `127.0.0.1:8000`.
- No cloud account, auth, telemetry, trading or background provider refresh. Provider/network reads require explicit Owner actions.
- Production and Test data, `.env`, backups, credentials and private exports never enter development workspaces or CI.
- CLOSED months remain immutable until explicit Reopen. Backend/domain is the financial source of truth.
- Exact money uses Decimal / integer minor units. Unknown/unavailable is never silently converted to zero.
- Filesystem housekeeping does not refresh providers, change financial data or promote a release.

## Major completed lines

### Monthly Close / UI v2

Native month/editor operations, explicit imports/Preview/Apply/readback, exact-month final review/report/reopen, Goals/Tax/IIS/Scenario and data/application tools are integrated. Home, Capital, Income and Plans, contextual History/Reports and native Monthly Close are primary v2 surfaces. `/v1` and retained legacy deep links remain intentionally available; #573 is CLOSED / NOT_PLANNED unless Owner explicitly revisits retirement later.

The post-release wave adds exact-month navigation, direct final review, saved-only reread, combined Settings/Diagnostics, collapsed bulk/individual future payouts, contextual verified mapping, exception-first Alfa, money/debt-editor readability and linked-pair explanation. Accepted lifecycle/financial boundaries remain unchanged.

Evidence: [UI completion](docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md), [default switch](docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md), [post-release UAT](docs/POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md).

### Decision Support v1

AI Analysis Bundle, Monthly Close Cockpit, Cash-flow Ladder, Risk & Allocation, Freshness & Provenance, Reconciliation, current-state Tax/IIS, deterministic Insights and Scenario Lab v1 are integrated. Scenario Lab is deterministic/read-only, not a market forecast. The AI export format has independent `schema_version=1.3.0`.

Closeout: [Decision Support v1](docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md).

### Performance and data integrity

Portfolio/account XIRR, exact TWRR, flow/valuation/membership/transfer/in-kind safeguards and PERF04A monetary bridge are integrated. Performance Phase A adds diagnostics and explicit data preparation. Exact class returns #535/#540 remain a separate Phase B, currently blocked on #534's accepted evidence prerequisites rather than on UI implementation.

`value_change_after_external_flows` is not return/profit/P&L. The accepted backend-only decomposition `B_portfolio = Σ B_account + Σ T_internal_transfer` has no residual bucket or partial exact split; instrument/class, price/FX, realised/unrealised and cost-basis attribution are unsupported without their own accepted evidence foundation. API/UI exposure of that backend slice is a separate decision.

Data-integrity #484–#498/#536–#539 and later #621–#624 preserve atomic writes, coherent SQLite reads, correct provenance, source coverage and stale-evidence invalidation. Missing accounts/periods are not zero-filled.

Evidence: [Performance v1](docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md), [component contract](docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md), [data-integrity closeout](docs/DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md).

### Recovery and durability

#417 is complete: explicit managed recovery-point publication/read-back, bounded per-protection-pair retention, isolated DR rehearsal, post-restore state reload and truthful ambiguous outcomes. Both the encrypted-destination contract and separately Owner-accepted plaintext synced-filesystem mode remain distinct. A synchronized folder is not automatically encrypted or proven delivered off-device. #543/PR #547 completed the separate CLI/retention hardening without reopening #417.

Evidence and supported commands: [durability closeout](docs/OWNER_DURABILITY_CLOSEOUT_2026-09-25.md), [Owner runtime operations](docs/OWNER_RUNTIME_OPERATIONS.md).

## Requirements

- Windows 10/11;
- Python 3.13 and [uv](https://docs.astral.sh/uv/);
- Node.js **22.23.1** (tested/recommended, `frontend/.nvmrc`) and npm; other permitted versions are declared by `frontend/package.json`, and `frontend/.npmrc` rejects unsupported engines;
- modern browser.

Docker/PostgreSQL/public web hosting are not required.

## Development installation

From an isolated clean development checkout, never production Stable:

```powershell
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
```

Dependencies remain locked by `backend/uv.lock` and `frontend/package-lock.json`. Each client creates task copies only under its configured workspace root; shared rules are in [AGENTS.md](AGENTS.md).

## Windows launcher — retired

The Windows Launcher GUI, package/install scripts and launcher-only
tests/CI jobs were removed from the repository by #629 after the Owner
removed the installed shell during #679. **Do not reinstall it to run Hermes
or to repair the folder layout.** Direct Prepare/Validate/Start below is the
normal path. Shared backup-first update (`scripts/launcher-production-backup.py`
via `update-stable-lib.ps1`), prepared-runtime, recovery rehearsal and
`RuntimeConfig` identity/exclusion helpers were preserved even where a helper
or schema name still mentions Launcher. Recovery and cleanup exclusion inputs
use the direct-operations runtime inventory defined in
[OWNER_RUNTIME_OPERATIONS §13](docs/OWNER_RUNTIME_OPERATIONS.md#13-protected-off-site-recovery-points-and-dr-rehearsal)
([example](docs/runtime-inventory.example.json)); no Launcher shell, config UI
or installation is involved. The former compact shell and failed
self-updater are historical: [R09 closeout](docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md).

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

Short readiness smoke:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

Prepare installs required locked dependencies, builds the frontend and records ignored exact-build proof. Start validates the proof; it does not silently install/build or move Git refs. A moved Windows Python environment can contain absolute interpreter paths: re-prepare its destination rather than blindly reusing console launchers. Never change the production DB binding to get around a startup failure.

## Explicit Stable release update

Run OPS02 from trusted canonical Main/Control, outside mutable Stable:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

It proves one published annotated release, makes a verified SQLite backup before Git mutation, pins that exact target, runs target Prepare + Validate and stops. It never chooses `latest`, follows main, starts Hermes, updates Test, publishes a release, runs DB migration or automatically rolls back/downgrades.

## Exact Preview/UAT preparation

Use the persistent Test location for the Preview role, with its own isolated data and one explicit candidate:

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

Existing-path guards remain authoritative; reuse the role/location, not an unsafe overwrite of Test data. Stop the owned runtime before changing its checkout. Only one runtime owns port 8000. [Owner runtime operations](docs/OWNER_RUNTIME_OPERATIONS.md) describe the supported boundaries.

## Release publication

Publication is separate from local installation. Permanent guarded Owner endpoint: **#124**; see [RELEASE_AUTOMATION](docs/RELEASE_AUTOMATION.md).

The sequence remains exact-SHA isolated UAT → Owner acceptance → guarded immutable publication → explicit backup-first OPS02 → explicit Start and health/data-continuity verification. The historical v0.9.0/v1.0.0 transitions remain proven; no new release follows automatically from a merged PR or a folder move.

## What comes next

- CI/test optimization #668–#671 and #629 Launcher retirement are complete; there is no dedicated test/CI optimization backlog. See [the closeout](docs/history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md).
- Focused #667 month-list retest and remaining portfolio/account Performance Owner checks can share one refreshed Test when selected; Owner has currently deferred this combined UAT to avoid repeating it before the Alfa follow-up settles.
- #646 is a separate Alfa PRO compatibility investigation. Current live evidence: Trading core can be switched Online on port 3366 and a read-only token can be issued, but Hermes still rejects the resulting protocol as unrecognized; no accepted token/handshake contract is available yet.
- #630, #573 and historical roadmap #127 are CLOSED / NOT_PLANNED; #528 is CLOSED / COMPLETED. Class returns #535/#540 and #389 composer remain product choices. `/v1` remains intentionally available.
- #679/#666 migration and janitor deployment are complete. Daily cleanup eligibility is described in [WORKSPACE_JANITOR](docs/WORKSPACE_JANITOR.md); it does not grant arbitrary manual deletion outside the root.

## Health

After a successful local start:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Published v1.2.0 reports `status=ok`, `version=1.2.0` after the local Stable update. Open `http://127.0.0.1:8000`.

## Documentation map

- [AGENTS.md](AGENTS.md): shared task entrypoint; [verification](docs/VERIFICATION_POLICY.md) and [routing](docs/MODEL_ROUTING.md) own their procedures.
- [MASTER_SPEC](docs/MASTER_SPEC.md): product semantics; accepted ADRs retain their contracts.
- [CURRENT_STATUS](docs/CURRENT_STATUS.md), [PROJECT_WIKI](docs/PROJECT_WIKI.md), [session closeout](docs/SESSION_CLOSEOUT_2026-10-03.md): active status/context and restart brief.
- [OWNER_MACHINE_LAYOUT](docs/OWNER_MACHINE_LAYOUT.md), [OWNER_RUNTIME_OPERATIONS](docs/OWNER_RUNTIME_OPERATIONS.md), [WORKSPACE_JANITOR](docs/WORKSPACE_JANITOR.md): current folders, direct startup and scheduled housekeeping.
- [EXECUTION_HISTORY](docs/EXECUTION_HISTORY.md), [CI/test optimization closeout](docs/history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md) and other dated closeouts retain history; historical model attribution is not a standing reporting requirement.
- [v1.2.0 release record](docs/releases/1.2.0.md), [v1.2.0 notes](docs/release-notes-1.2.0.md), [v1.1.0 release record](docs/releases/1.1.0.md), [v1.0.0 closeout](docs/R10_RELEASE_CLOSEOUT_2026-09-21.md): immutable release-era evidence, not instructions to redo completed work.

## Privacy

Never commit real `.env`, production/Test DBs, SQLite sidecars/backups, provider credentials, private exports/PDFs or reconstructive personal datasets. Development and CI use synthetic fixtures. Ordinary model handoffs do not request or record model/provider identity or benchmarks.
