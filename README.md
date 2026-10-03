# Hermes Finance

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Оно помогает закрывать месяц, видеть ликвидный капитал и долги, анализировать инвестиционный результат и пассивный доход, работать с целями/Tax/IIS/Scenario Lab, проверять reconciliation/freshness и экспортировать read-only AI Analysis Bundle.

## Current status

Published/local Stable remains **v1.1.0**: released commit `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`, tree `7f5a3198fa650b71545550301063c9afd887f8f8`, annotated tag object `9b402190bafc5d8415b217580da5e18ed35a6331`. Publication was 2026-09-30 UTC; release push CI `36776904188` and Guarded Release `36777962224` succeeded. #643/#644 and the [release record](docs/releases/1.1.0.md) own the publication evidence.

#572 is CLOSED with **Owner PASS WITH DOCUMENTED LIMITATIONS**, including manual/v1 use and provider limitations. The earlier pre-publication deferral is historical, superseded by [actual Owner acceptance](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5937693786), not retroactively relabelled as an earlier PASS. UI v2 is primary at `/`; the previous UI stays at `/v1`.

**Development main is ahead of Stable.** The post-release six-slice wave (#645, #647–#651) passed Owner UAT with documented follow-ups and was integrated through #662. #672 removed repeated Home qualifiers; #667/#674 implemented the month-list follow-up. This is not a new release or a Stable version upgrade. Historical September quotes do not prove live same-day LAST; #646 remains a separate Alfa transport question.

**Filesystem migration is complete:** #679/#666 moved Stable/Main/persistent Test, removed the authorized legacy forest and deployed daily workspace cleanup through #685. Local Launcher/config/shortcuts were removed. Repository Launcher retirement is still #629. The [machine-layout contract](docs/OWNER_MACHINE_LAYOUT.md) also protects the separate active Ops installation; outside the Hermes root does not automatically mean disposable.

Session checkpoint before this documentation sync: `main@8eb991fc81ebbe63917a9ca1ea204762129c9019`, exact-main CI `37150791634` SUCCESS. Live GitHub remains authoritative. See [CURRENT_STATUS](docs/CURRENT_STATUS.md) and the [2026-10-03 session closeout](docs/SESSION_CLOSEOUT_2026-10-03.md) for completed work, test-stream ownership and remaining Owner checks.

## Product/runtime invariants

- Windows 10/11, single user, local-only, local SQLite; normal endpoint `127.0.0.1:8000`.
- No cloud account, auth, telemetry, trading or background provider refresh. Provider/network reads require explicit Owner actions.
- Production and Test data, `.env`, backups, credentials and private exports never enter development workspaces or CI.
- CLOSED months remain immutable until explicit Reopen. Backend/domain is the financial source of truth.
- Exact money uses Decimal / integer minor units. Unknown/unavailable is never silently converted to zero.
- Filesystem housekeeping does not refresh providers, change financial data or promote a release.

## Major completed lines

### Monthly Close / UI v2

Native month/editor operations, explicit imports/Preview/Apply/readback, exact-month final review/report/reopen, Goals/Tax/IIS/Scenario and data/application tools are integrated. Home, Capital, Income and Plans, contextual History/Reports and native Monthly Close are primary v2 surfaces. `/v1` and retained legacy deep links remain available; #573 retirement requires a separate Owner decision.

The post-release wave adds exact-month navigation, direct final review, saved-only reread, combined Settings/Diagnostics, collapsed bulk/individual future payouts, contextual verified mapping, exception-first Alfa, money/debt-editor readability and linked-pair explanation. Accepted lifecycle/financial boundaries remain unchanged.

Evidence: [UI completion](docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md), [default switch](docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md), [post-release UAT](docs/POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md).

### Decision Support v1

AI Analysis Bundle, Monthly Close Cockpit, Cash-flow Ladder, Risk & Allocation, Freshness & Provenance, Reconciliation, current-state Tax/IIS, deterministic Insights and Scenario Lab v1 are integrated. Scenario Lab is deterministic/read-only, not a market forecast. The AI export format has independent `schema_version=1.3.0`.

Closeout: [Decision Support v1](docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md).

### Performance and data integrity

Portfolio/account XIRR, exact TWRR, flow/valuation/membership/transfer/in-kind safeguards and PERF04A monetary bridge are integrated. Performance Phase A adds diagnostics and explicit data preparation; class returns #535/#540 remain a separate Phase B.

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

## Windows launcher — retired locally

The Owner removed the installed Launcher/config and shortcuts during #679. **Do not reinstall it to run Hermes or to repair the new folder layout.** Direct Prepare/Validate/Start is the normal path. #629 removes remaining repository Launcher source/package/tests/workflows after checking shared runtime/recovery consumers. Their presence in source or an old release does not make installation a current requirement.

The former compact shell and failed self-updater are historical: [R09 closeout](docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md). Local shell removal does not permit deleting shared backup, prepared-runtime or recovery helpers just because their names mention Launcher.

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

- Existing CI stream: #671/#681, #668/#682 and #669/#683 are merged; #670 docs-only PR fast path remains. Preserve actual head/merge evidence, unique tests and full canonical main/release gates.
- #629 repository Launcher retirement is the next technical candidate, serialized with shared CI changes.
- Focused #667 month-list retest and remaining portfolio/account Performance Owner checks can share one refreshed Test when selected. Full accepted UAT is not repeated for this documentation sync.
- #646 is a separate Alfa investigation. #630 representative fixture, class returns #535/#540 and #389 composer are deferred choices. `/v1` is not retired.
- #679/#666 migration and janitor deployment are complete. Daily cleanup eligibility is described in [WORKSPACE_JANITOR](docs/WORKSPACE_JANITOR.md); it does not grant arbitrary manual deletion outside the root.

## Health

After a successful local start:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Published v1.1.0 reports `status=ok`, `version=1.1.0`. Open `http://127.0.0.1:8000`.

## Documentation map

- [AGENTS.md](AGENTS.md): shared task entrypoint; [verification](docs/VERIFICATION_POLICY.md) and [routing](docs/MODEL_ROUTING.md) own their procedures.
- [MASTER_SPEC](docs/MASTER_SPEC.md): product semantics; accepted ADRs retain their contracts.
- [CURRENT_STATUS](docs/CURRENT_STATUS.md), [PROJECT_WIKI](docs/PROJECT_WIKI.md), [session closeout](docs/SESSION_CLOSEOUT_2026-10-03.md): active status/context and restart brief.
- [OWNER_MACHINE_LAYOUT](docs/OWNER_MACHINE_LAYOUT.md), [OWNER_RUNTIME_OPERATIONS](docs/OWNER_RUNTIME_OPERATIONS.md), [WORKSPACE_JANITOR](docs/WORKSPACE_JANITOR.md): current folders, direct startup and scheduled housekeeping.
- [EXECUTION_HISTORY](docs/EXECUTION_HISTORY.md) and dated closeouts retain history; historical model attribution is not a standing reporting requirement.
- [v1.1.0 release record](docs/releases/1.1.0.md), [v1.1.0 notes](docs/release-notes-1.1.0.md), [v1.0.0 closeout](docs/R10_RELEASE_CLOSEOUT_2026-09-21.md), [v0.9.0 notes](docs/release-notes-0.9.0.md): immutable release-era evidence, not instructions to redo completed work.

## Privacy

Never commit real `.env`, production/Test DBs, SQLite sidecars/backups, provider credentials, private exports/PDFs or reconstructive personal datasets. Development and CI use synthetic fixtures. Ordinary model handoffs do not request or record model/provider identity or benchmarks.
